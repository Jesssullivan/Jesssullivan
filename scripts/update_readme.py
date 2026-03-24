#!/usr/bin/env python3
"""Update the profile README with latest repo data from GitHub GraphQL API.

FP pipeline: effects at edges, pure transforms in the middle.
Uses only stdlib + urllib (no pip installs needed).
"""

import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from shared import (
    BlogPost,
    CategorizedRepo,
    FossContribution,
    categorize_repo,
    format_atom_date,
    format_iso_date,
    format_rss_date,
    graphql_request,
    load_config,
    parse_repo,
    pipe,
)

README_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "README.md")


# --- GraphQL queries ---

REPOS_QUERY = """
{{
  user(login: "{user}") {{
    repositories(first: 50, ownerAffiliations: [OWNER], orderBy: {{field: PUSHED_AT, direction: DESC}}, privacy: PUBLIC{after}) {{
      pageInfo {{
        hasNextPage
        endCursor
      }}
      nodes {{
        name
        description
        url
        primaryLanguage {{ name }}
        languages(first: 10, orderBy: {{field: SIZE, direction: DESC}}) {{
          totalSize
          edges {{ size node {{ name color }} }}
        }}
        repositoryTopics(first: 10) {{
          nodes {{
            topic {{ name }}
          }}
        }}
        stargazerCount
        isFork
        pushedAt
        parent {{ nameWithOwner }}
      }}
    }}
  }}
}}
"""

FOSS_QUERY = """
{{
  user(login: "{user}") {{
    repositoriesContributedTo(
      first: 100,
      includeUserRepositories: false,
      contributionTypes: [COMMIT, PULL_REQUEST, PULL_REQUEST_REVIEW]
    ) {{
      totalCount
      nodes {{
        nameWithOwner
        name
        url
        description
        primaryLanguage {{ name }}
        languages(first: 5, orderBy: {{field: SIZE, direction: DESC}}) {{
          edges {{ size node {{ name color }} }}
        }}
        stargazerCount
      }}
    }}
  }}
}}
"""


ORG_REPOS_QUERY = """
{{
  organization(login: "{org}") {{
    repositories(first: 50, orderBy: {{field: PUSHED_AT, direction: DESC}}, privacy: PUBLIC{after}) {{
      pageInfo {{
        hasNextPage
        endCursor
      }}
      nodes {{
        name
        description
        url
        primaryLanguage {{ name }}
        languages(first: 10, orderBy: {{field: SIZE, direction: DESC}}) {{
          totalSize
          edges {{ size node {{ name color }} }}
        }}
        repositoryTopics(first: 10) {{
          nodes {{
            topic {{ name }}
          }}
        }}
        stargazerCount
        isFork
        pushedAt
        parent {{ nameWithOwner }}
      }}
    }}
  }}
}}
"""


# --- Fetch functions (effects boundary) ---


def fetch_own_repos(config, token):
    """Fetch all public repos via paginated GraphQL."""
    all_nodes = []
    cursor = None
    while True:
        after = f', after: "{cursor}"' if cursor else ""
        query = REPOS_QUERY.format(user=config.user, after=after)
        data = graphql_request(token, query)
        repos_data = data["data"]["user"]["repositories"]
        all_nodes.extend(repos_data["nodes"])
        page_info = repos_data["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        cursor = page_info["endCursor"]
    return all_nodes


def fetch_org_repos(org, token):
    """Fetch all public repos for an organization via paginated GraphQL."""
    all_nodes = []
    cursor = None
    while True:
        after = f', after: "{cursor}"' if cursor else ""
        query = ORG_REPOS_QUERY.format(org=org, after=after)
        data = graphql_request(token, query)
        repos_data = data["data"]["organization"]["repositories"]
        all_nodes.extend(repos_data["nodes"])
        page_info = repos_data["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        cursor = page_info["endCursor"]
    return all_nodes


def fetch_foss_contributions(config, token):
    """Fetch repos contributed to (excluding own repos)."""
    query = FOSS_QUERY.format(user=config.user)
    data = graphql_request(token, query)
    return data["data"]["user"]["repositoriesContributedTo"]["nodes"]


def fetch_blog_posts(config):
    """Fetch latest blog posts from RSS/Atom feed."""
    import urllib.request

    try:
        req = urllib.request.Request(
            config.blog_feed_url,
            headers={"User-Agent": "profile-readme-updater"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_data = resp.read()
    except Exception as exc:
        print(f"Warning: could not fetch blog feed: {exc}")
        return []

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as exc:
        print(f"Warning: could not parse blog feed XML: {exc}")
        return []

    posts = []
    count = config.blog_post_count

    # Try RSS 2.0 first
    channel = root.find("channel")
    if channel is not None:
        for item in channel.findall("item")[:count]:
            title = item.findtext("title", "Untitled")
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            posts.append(BlogPost(title=title, link=link, date=format_rss_date(pub_date)))
        return posts

    # Try Atom format
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", ns) or root.findall("entry")
    for entry in entries[:count]:
        title = entry.findtext("atom:title", None, ns)
        if title is None:
            title = entry.findtext("title", "Untitled")
        link_el = entry.find("atom:link", ns) or entry.find("link")
        link = link_el.get("href", "") if link_el is not None else ""
        updated = entry.findtext("atom:updated", None, ns) or entry.findtext("updated", "")
        published = entry.findtext("atom:published", None, ns) or entry.findtext("published", updated)
        posts.append(BlogPost(title=title, link=link, date=format_atom_date(published)))

    return posts


# --- Pure filter/transform ---


def should_include(repo, blocklist):
    """Return True if the repo should appear in the README."""
    blocklist_lower = {b.lower() for b in blocklist}
    if repo.name.lower() in blocklist_lower:
        return False
    if not repo.description and not repo.primary_language:
        return False
    return True


def parse_foss(node):
    """Convert a raw GraphQL FOSS contribution node to FossContribution."""
    primary = node.get("primaryLanguage")
    langs = [
        (e["node"]["name"], e.get("size", 0), e["node"].get("color", ""))
        for e in node.get("languages", {}).get("edges", [])
    ]
    return FossContribution(
        name=node["name"],
        name_with_owner=node["nameWithOwner"],
        url=node["url"],
        description=node.get("description") or "",
        primary_language=primary["name"] if primary else "",
        languages=langs,
        stars=node.get("stargazerCount", 0),
    )


def group_by_category(categorized_repos, category_order):
    """Group CategorizedRepo list by category, preserving order."""
    groups = {cat: [] for cat in category_order}
    for cr in categorized_repos:
        groups.setdefault(cr.category, []).append(cr)
    return groups


# --- Renderers (pure) ---


def render_project_list(grouped, config, org_label=None):
    """Render categorized repos as bullet lists sorted by pushed_at.

    Skips repos with no description. If org_label is set, prefixes
    category names with the org (e.g. "tinyland-inc / Infrastructure & DevOps").
    """
    total_shown = 0
    lines = []
    for cat in config.category_order:
        cat_repos = grouped.get(cat, [])
        # Filter out repos with no description
        cat_repos = [cr for cr in cat_repos if cr.repo.description]
        if not cat_repos:
            continue
        # Sort by pushed_at descending within category
        cat_repos = sorted(cat_repos, key=lambda cr: cr.repo.pushed_at, reverse=True)
        total_shown += len(cat_repos)
        label = f"{org_label} / {cat}" if org_label else cat
        lines.append(f"<details>")
        lines.append(f"<summary><strong>{label}</strong> ({len(cat_repos)})</summary>")
        lines.append("")
        for cr in cat_repos:
            r = cr.repo
            desc = r.description.replace("|", "\\|")
            if len(desc) > 100:
                desc = desc[:97] + "..."
            meta_parts = []
            if r.primary_language:
                meta_parts.append(r.primary_language)
            if r.stars > 0:
                meta_parts.append(f"{r.stars} \u2605")
            pushed = format_iso_date(r.pushed_at)
            if pushed:
                meta_parts.append(pushed)
            meta = f" *({' \u00b7 '.join(meta_parts)})*" if meta_parts else ""
            if desc:
                lines.append(f"- [**{r.name}**]({r.url}) \u2014 {desc}{meta}")
            else:
                lines.append(f"- [**{r.name}**]({r.url}){meta}")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    remaining = sum(len(v) for v in grouped.values()) - total_shown
    if remaining > 0:
        lines.append(
            f"*...and [{remaining} more](https://github.com/{config.user}?tab=repositories&type=source)*"
        )
    return "\n".join(lines)


def render_foss_section(foss_list, user):
    """Render FOSS contributions as a bullet list.

    Filters out repos with no description, sorts external orgs first
    (by stars desc), then own-org repos (by stars desc).
    """
    if not foss_list:
        return ""

    # Filter: only show repos that have a description
    with_desc = [f for f in foss_list if f.description]

    if not with_desc:
        return ""

    # Split into external (true FOSS) vs own-org (tinyland-inc, etc.)
    user_lower = user.lower()
    external = []
    own_org = []
    for f in with_desc:
        owner = f.name_with_owner.split("/")[0].lower()
        if owner == user_lower:
            continue  # skip repos owned by the user directly
        # Heuristic: if the org name appears in the user's own repo names
        # or if user is a member, treat as own-org. For now, use a simple
        # check — repos from orgs where user has many contributions.
        external.append(f)

    # Sort each group: stars descending, then alphabetically
    external.sort(key=lambda f: (-f.stars, f.name_with_owner.lower()))

    lines = [
        "<details>",
        f"<summary><strong>FOSS Contributions</strong> ({len(external)})</summary>",
        "",
    ]
    for f in external:
        lang_part = f" *({f.primary_language})*" if f.primary_language else ""
        desc = f.description
        if len(desc) > 80:
            desc = desc[:77] + "..."
        lines.append(f"- [**{f.name_with_owner}**]({f.url}) \u2014 {desc}{lang_part}")
    lines.append("")
    lines.append("</details>")
    return "\n".join(lines)


def render_blog_section(posts):
    """Render blog posts as a bullet list."""
    lines = ["### Latest Blog Posts", ""]
    for post in posts:
        date_part = f" \u2014 *{post.date}*" if post.date else ""
        lines.append(f"- [{post.title}]({post.link}){date_part}")
    lines.append("")
    lines.append("[Read more ->](https://transscendsurvival.org/blog)")
    return "\n".join(lines)


# --- Section updater ---


def update_section(content, section_name, new_content):
    """Replace content between START_SECTION and END_SECTION markers."""
    pattern = rf"(<!--START_SECTION:{section_name}-->).*?(<!--END_SECTION:{section_name}-->)"
    replacement = rf"\1\n{new_content}\n\2"
    return re.sub(pattern, replacement, content, flags=re.DOTALL)


# --- JSON serialization helpers ---


def repo_to_dict(repo):
    """Convert Repo dataclass back to the JSON format expected by graph/stats scripts."""
    return {
        "name": repo.name,
        "description": repo.description,
        "url": repo.url,
        "primaryLanguage": {"name": repo.primary_language} if repo.primary_language else None,
        "languages": {
            "totalSize": repo.total_lang_size,
            "edges": [
                {"size": size, "node": {"name": name, "color": color}}
                for name, size, color in repo.languages
            ],
        },
        "repositoryTopics": {
            "nodes": [{"topic": {"name": t}} for t in repo.topics]
        },
        "stargazerCount": repo.stars,
        "isFork": repo.is_fork,
        "pushedAt": repo.pushed_at,
        "parent": {"nameWithOwner": repo.parent} if repo.parent else None,
    }


def categorized_to_dict(cr):
    """Convert CategorizedRepo to JSON-serializable dict."""
    d = repo_to_dict(cr.repo)
    d["category"] = cr.category
    return d


# --- Main pipeline ---


def _run_pipeline(nodes, config):
    """Shared parse/filter/categorize pipeline for a list of raw repo nodes."""
    return pipe(
        nodes,
        lambda ns: [parse_repo(n) for n in ns],
        lambda repos: [r for r in repos if should_include(r, config.blocklist)],
        lambda repos: [r for r in repos if not r.is_fork],
        lambda repos: [categorize_repo(r, config) for r in repos],
    )


def _foss_to_dict(fc):
    """Convert FossContribution to JSON-serializable dict."""
    return {
        "nameWithOwner": fc.name_with_owner,
        "name": fc.name,
        "url": fc.url,
        "description": fc.description,
        "primaryLanguage": {"name": fc.primary_language} if fc.primary_language else None,
        "languages": {
            "edges": [
                {"size": size, "node": {"name": name, "color": color}}
                for name, size, color in fc.languages
            ]
        },
        "stargazerCount": fc.stars,
    }


def main():
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("Error: GITHUB_TOKEN not set")
        return

    config = load_config()

    # Effects boundary: fetch personal repos
    print("Fetching personal repos...")
    raw_repos = fetch_own_repos(config, token)
    print(f"Fetched {len(raw_repos)} personal repos")

    # Fetch org repos
    raw_org_repos = {}
    for org in config.orgs:
        print(f"Fetching {org} repos...")
        raw_org_repos[org] = fetch_org_repos(org, token)
        print(f"Fetched {len(raw_org_repos[org])} repos from {org}")

    # Fetch FOSS contributions
    print("Fetching FOSS contributions...")
    raw_foss = fetch_foss_contributions(config, token)
    print(f"Fetched {len(raw_foss)} FOSS contributions (raw)")

    blog_posts = fetch_blog_posts(config)
    print(f"Fetched {len(blog_posts)} blog posts")

    # Pure pipeline — personal repos
    personal_result = _run_pipeline(raw_repos, config)
    personal_grouped = group_by_category(personal_result, config.category_order)
    print(f"Personal: {len(personal_result)} repos in {len([k for k, v in personal_grouped.items() if v])} categories")

    # Pure pipeline — org repos
    org_results = {}
    for org, nodes in raw_org_repos.items():
        org_results[org] = _run_pipeline(nodes, config)
        print(f"Org {org}: {len(org_results[org])} repos")

    # FOSS: parse all for stats count, filter for display
    all_foss = [parse_foss(n) for n in raw_foss]
    exclusions_lower = {o.lower() for o in config.org_exclusions_for_foss}
    foss_display = [
        f for f in all_foss
        if f.name_with_owner.split("/")[0].lower() not in exclusions_lower
    ]
    print(f"FOSS: {len(all_foss)} total, {len(foss_display)} external (excluding {list(exclusions_lower)})")

    # Effects boundary: write intermediate data
    out_dir = os.path.dirname(os.path.dirname(__file__))

    # repos_data.json — personal only (feeds star count + language stats)
    repos_json_path = os.path.join(out_dir, "repos_data.json")
    with open(repos_json_path, "w") as f:
        json.dump([repo_to_dict(cr.repo) for cr in personal_result], f)
    print(f"Wrote {len(personal_result)} personal repos to repos_data.json")

    # org_repos_data.json — org repos (optional lang stats inclusion)
    all_org_categorized = []
    for org_list in org_results.values():
        all_org_categorized.extend(org_list)
    org_repos_json_path = os.path.join(out_dir, "org_repos_data.json")
    with open(org_repos_json_path, "w") as f:
        json.dump([repo_to_dict(cr.repo) for cr in all_org_categorized], f)
    print(f"Wrote {len(all_org_categorized)} org repos to org_repos_data.json")

    # categorized_repos.json — personal + org combined (feeds graph)
    all_categorized = list(personal_result) + all_org_categorized
    categorized_json_path = os.path.join(out_dir, "categorized_repos.json")
    with open(categorized_json_path, "w") as f:
        json.dump([categorized_to_dict(cr) for cr in all_categorized], f)
    print(f"Wrote {len(all_categorized)} total repos to categorized_repos.json")

    # foss_data.json — ALL FOSS (full count for stats card)
    foss_json_path = os.path.join(out_dir, "foss_data.json")
    with open(foss_json_path, "w") as f:
        json.dump([_foss_to_dict(fc) for fc in all_foss], f)
    print(f"Wrote {len(all_foss)} FOSS contributions to foss_data.json")

    # Subprocess: graph & stats generation
    scripts_dir = os.path.dirname(__file__)
    try:
        subprocess.run([sys.executable, os.path.join(scripts_dir, "generate_graph.py")], check=True)
        print("Generated repo relationship graphs")
    except Exception as exc:
        print(f"Warning: graph generation failed: {exc}")

    try:
        subprocess.run([sys.executable, os.path.join(scripts_dir, "generate_stats.py")], check=True)
        print("Generated stats SVG cards")
    except Exception as exc:
        print(f"Warning: stats generation failed: {exc}")

    # Pure: render sections
    # Apply max_repos cap if nonzero
    if config.max_repos > 0:
        limited_grouped = {}
        shown = 0
        for cat in config.category_order:
            cat_repos = personal_grouped.get(cat, [])
            take = min(len(cat_repos), config.max_repos - shown)
            limited_grouped[cat] = cat_repos[:take]
            shown += take
            if shown >= config.max_repos:
                break
    else:
        limited_grouped = personal_grouped

    # Render personal repos
    personal_section = render_project_list(limited_grouped, config)

    # Render org repos as separate accordion groups per org
    org_section_parts = []
    for org, org_list in org_results.items():
        org_grouped = group_by_category(org_list, config.category_order)
        org_rendered = render_project_list(org_grouped, config, org_label=org)
        if org_rendered.strip():
            org_section_parts.append(org_rendered)

    repos_section = personal_section
    if org_section_parts:
        repos_section += "\n" + "\n".join(org_section_parts)

    sections = {
        "repos": repos_section,
        "foss": render_foss_section(foss_display, config.user),
        "blog": render_blog_section(blog_posts) if blog_posts else None,
    }

    # Effects boundary: write README
    with open(README_PATH, "r") as f:
        content = f.read()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    total_shown = len(personal_result) + len(all_org_categorized)
    repo_content = "\n" + sections["repos"] + "\n" + f"*Last updated: {now}*"
    content = update_section(content, "repos", repo_content)
    print(f"Updated repos section: {total_shown} shown")

    if sections["foss"]:
        content = update_section(content, "foss", sections["foss"])
        print(f"Updated FOSS section: {len(foss_display)} displayed, {len(all_foss)} total")

    if sections["blog"]:
        content = update_section(content, "blog", sections["blog"])
        print(f"Updated blog section: {len(blog_posts)} posts")
    else:
        print("Skipping blog section update (no posts fetched)")

    with open(README_PATH, "w") as f:
        f.write(content)

    print("Done.")


if __name__ == "__main__":
    main()
