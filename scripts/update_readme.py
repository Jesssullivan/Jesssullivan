#!/usr/bin/env python3
"""Update the profile README with latest repo data from GitHub GraphQL API.

Uses only stdlib + urllib (no pip installs needed).
"""

import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GRAPHQL_URL = "https://api.github.com/graphql"
README_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "README.md")

# Repos to exclude from the README entirely
BLOCKLIST = {
    "test", "testing", "test-repo", "hello-world",
    "Jesssullivan",  # profile repo itself
    "jesssullivan.github.io",  # blog repo (shown separately)
    "misc", "sk-blog-1", "cal-com-testing",
    "TarrytownNY-Notes", "MembershipWorks-Migration",
    "DLADocs", "dla-hugo", "pages_columbari",
    "stub_mo_image_classify", "tmpUI",
}

# Limits for table sizes
MAX_ORIGINAL_REPOS = 30

# Category mappings: repo name -> category
# Repos not listed here are auto-categorized by language
REPO_CATEGORIES = {
    # Languages & Compilers
    "quickchpl": "Languages & Compilers",
    "aoc-2025": "Languages & Compilers",
    "RemoteJuggler": "Languages & Compilers",
    "pixelwise-research": "Languages & Compilers",
    # Infrastructure & DevOps
    "GloriousFlywheel": "Infrastructure & DevOps",
    "Ansible-DAG-Harness": "Infrastructure & DevOps",
    "betterkvm": "Infrastructure & DevOps",
    "tinyscale-mikrotik": "Infrastructure & DevOps",
    "searchies": "Infrastructure & DevOps",
    "ts-caddy": "Infrastructure & DevOps",
    "HCI-notes": "Infrastructure & DevOps",
    "tinyland-cleanup": "Infrastructure & DevOps",
    "tinyland-kdbx": "Infrastructure & DevOps",
    "tinywaffle": "Infrastructure & DevOps",
    "pp": "Infrastructure & DevOps",
    "DarwinNicUtil": "Infrastructure & DevOps",
    # Hardware & Maker
    "XoxdWM": "Hardware & Maker",
    "hiberpower-ntfs": "Hardware & Maker",
    "TurkeyProbe": "Hardware & Maker",
    "Arduino_Coil_Winder": "Hardware & Maker",
    # ML & Ecology
    "MerlinAI-Interpreters": "ML & Ecology",
    "gnucashr": "ML & Data",
    "AccuWixReport": "ML & Data",
    # Web & Apps
    "tetrahedron": "Web & Apps",
    "FastPhotoAPI": "Web & Apps",
    "timberbuddy": "Web & Apps",
    "IntroTypeScript": "Web & Apps",
    "GIS_Shortcuts": "Web & Apps",
}

# Language -> category fallback
LANG_CATEGORY = {
    "Chapel": "Languages & Compilers",
    "Futhark": "Languages & Compilers",
    "Haskell": "Languages & Compilers",
    "HCL": "Infrastructure & DevOps",
    "Nix": "Infrastructure & DevOps",
    "Shell": "Infrastructure & DevOps",
    "Dockerfile": "Infrastructure & DevOps",
    "Jinja": "Infrastructure & DevOps",
    "C++": "Hardware & Maker",
    "C": "Hardware & Maker",
    "Zig": "Hardware & Maker",
    "Emacs Lisp": "Hardware & Maker",
    "R": "ML & Data",
    "Jupyter Notebook": "ML & Data",
}

QUERY = """
{
  user(login: "Jesssullivan") {
    repositories(first: 50, orderBy: {field: PUSHED_AT, direction: DESC}, privacy: PUBLIC) {
      nodes {
        name
        description
        url
        primaryLanguage { name }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          nodes { name }
        }
        repositoryTopics(first: 10) {
          nodes {
            topic { name }
          }
        }
        stargazerCount
        isFork
        pushedAt
        parent { nameWithOwner }
      }
    }
  }
}
"""


def fetch_repos():
    """Fetch public repos via GitHub GraphQL API.

    Tries urllib first, falls back to `gh api graphql` subprocess.
    """
    import subprocess

    # Try urllib first (works in GitHub Actions with GITHUB_TOKEN)
    try:
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "profile-readme-updater",
        }
        payload = json.dumps({"query": QUERY}).encode("utf-8")
        req = urllib.request.Request(GRAPHQL_URL, data=payload, headers=headers)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if "errors" in data:
            raise RuntimeError(f"GraphQL errors: {data['errors']}")
        return data["data"]["user"]["repositories"]["nodes"]
    except Exception as exc:
        print(f"urllib failed ({exc}), trying gh cli...")

    # Fallback: use gh cli (works locally with gh auth)
    result = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={QUERY}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh api failed: {result.stderr}")
    data = json.loads(result.stdout)
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data["data"]["user"]["repositories"]["nodes"]


def should_include(repo):
    """Return True if the repo should appear in the README."""
    name = repo["name"]
    if name.lower() in {b.lower() for b in BLOCKLIST}:
        return False
    # Exclude repos with no description AND no primary language
    has_desc = bool(repo.get("description"))
    has_lang = bool(repo.get("primaryLanguage"))
    if not has_desc and not has_lang:
        return False
    return True


def build_activity_section(repos):
    """Build the 'Currently working on' section from the most recently pushed repo."""
    if not repos:
        return ""
    top = repos[0]
    name = top["name"]
    url = top["url"]
    desc = top.get("description") or ""
    lang = top.get("primaryLanguage")
    lang_name = lang["name"] if lang else ""
    pushed = top.get("pushedAt", "")
    pushed_nice = _format_iso_date(pushed) if pushed else ""

    lines = [
        f"**Currently working on:** [{name}]({url})",
    ]
    if desc:
        lines.append(f"  {desc}")
    parts = []
    if lang_name:
        parts.append(lang_name)
    if pushed_nice:
        parts.append(f"last push {pushed_nice}")
    if parts:
        lines.append(f"  *{' · '.join(parts)}*")
    return "\n".join(lines)


def _categorize_repo(repo):
    """Assign a category to a repo based on name or language."""
    name = repo["name"]
    if name in REPO_CATEGORIES:
        return REPO_CATEGORIES[name]
    lang = repo.get("primaryLanguage")
    lang_name = lang["name"] if lang else ""
    if lang_name in LANG_CATEGORY:
        return LANG_CATEGORY[lang_name]
    return "Other"


def build_original_table(repos):
    """Build categorized repo showcase, limited to MAX_ORIGINAL_REPOS."""
    shown = repos[:MAX_ORIGINAL_REPOS]

    # Group by category
    categories = {}
    for repo in shown:
        cat = _categorize_repo(repo)
        categories.setdefault(cat, []).append(repo)

    # Render in preferred order
    cat_order = [
        "Languages & Compilers",
        "Infrastructure & DevOps",
        "Hardware & Maker",
        "ML & Data",
        "Web & Apps",
        "Other",
    ]
    lines = []
    for cat in cat_order:
        cat_repos = categories.get(cat, [])
        if not cat_repos:
            continue
        lines.append(f"**{cat}**")
        lines.append("")
        lines.append("| Repo | Description | Languages | Topics |")
        lines.append("|------|-------------|-----------|--------|")
        for repo in cat_repos:
            name = repo["name"]
            desc = (repo["description"] or "").replace("|", "\\|")
            if len(desc) > 100:
                desc = desc[:97] + "..."

            # Languages - primary bold, others normal
            primary = repo.get("primaryLanguage")
            primary_name = primary["name"] if primary else ""
            all_langs = [n["name"] for n in repo.get("languages", {}).get("nodes", [])]
            if primary_name and all_langs:
                others = [l for l in all_langs if l != primary_name]
                lang_str = f"**{primary_name}**"
                if others:
                    lang_str += ", " + ", ".join(others[:3])
            elif primary_name:
                lang_str = f"**{primary_name}**"
            else:
                lang_str = ""

            # Topics
            topics = [n["topic"]["name"] for n in repo.get("repositoryTopics", {}).get("nodes", [])]
            topic_str = ", ".join(topics[:4]) if topics else ""

            url = repo["url"]
            lines.append(f"| [{name}]({url}) | {desc} | {lang_str} | {topic_str} |")
        lines.append("")

    remaining = len(repos) - len(shown)
    if remaining > 0:
        lines.append(f"*...and [{remaining} more](https://github.com/Jesssullivan?tab=repositories&type=source)*")
    return "\n".join(lines)


def build_forks_table(repos):
    """Build compact list for forked repos, limited to MAX_FORKS."""
    # Prioritize forks with descriptions and stars
    scored = sorted(repos, key=lambda r: (r.get("stargazerCount", 0), bool(r.get("description"))), reverse=True)
    shown = scored[:MAX_FORKS]
    lines = ["| Fork | Upstream |", "|------|----------|"]
    for repo in shown:
        name = repo["name"]
        parent = repo.get("parent", {})
        upstream = parent.get("nameWithOwner", "") if parent else ""
        badge = f"![](https://img.shields.io/github/stars/Jesssullivan/{name}?style=social&label={name})"
        upstream_link = f"[{upstream}](https://github.com/{upstream})" if upstream else ""
        lines.append(f"| {badge} | {upstream_link} |")
    remaining = len(repos) - len(shown)
    if remaining > 0:
        lines.append("")
        lines.append(f"*...and [{remaining} more forks](https://github.com/Jesssullivan?tab=repositories&type=fork)*")
    return "\n".join(lines)


def _format_iso_date(date_str):
    """Format an ISO 8601 date string into a relative or readable date."""
    if not date_str:
        return ""
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - dt
        if delta.days == 0:
            return "today"
        elif delta.days == 1:
            return "yesterday"
        elif delta.days < 7:
            return f"{delta.days} days ago"
        elif delta.days < 30:
            weeks = delta.days // 7
            return f"{weeks} week{'s' if weeks > 1 else ''} ago"
        else:
            return dt.strftime("%b %d, %Y")
    except (ValueError, TypeError):
        return date_str[:10]


# --- Blog feed ---

BLOG_FEED_URL = "https://transscendsurvival.org/feed.xml"
BLOG_POST_COUNT = 3


def fetch_blog_posts():
    """Fetch the latest blog posts from the RSS feed."""
    try:
        req = urllib.request.Request(
            BLOG_FEED_URL,
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

    # Try RSS 2.0 first
    channel = root.find("channel")
    if channel is not None:
        items = channel.findall("item")
        for item in items[:BLOG_POST_COUNT]:
            title = item.findtext("title", "Untitled")
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            posts.append({"title": title, "link": link, "date": _format_rss_date(pub_date)})
        return posts

    # Try Atom format
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    atom_entries = root.findall("atom:entry", ns)
    if not atom_entries:
        atom_entries = root.findall("entry")
    for entry in atom_entries[:BLOG_POST_COUNT]:
        title = entry.findtext("atom:title", None, ns)
        if title is None:
            title = entry.findtext("title", "Untitled")
        link_el = entry.find("atom:link", ns)
        if link_el is None:
            link_el = entry.find("link")
        link = link_el.get("href", "") if link_el is not None else ""
        updated = entry.findtext("atom:updated", None, ns)
        if updated is None:
            updated = entry.findtext("updated", "")
        published = entry.findtext("atom:published", None, ns)
        if published is None:
            published = entry.findtext("published", updated)
        posts.append({"title": title, "link": link, "date": _format_atom_date(published)})

    return posts


def _format_rss_date(date_str):
    """Parse an RSS pubDate string into a readable format like 'Jan 15, 2026'."""
    if not date_str:
        return ""
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime("%b %d, %Y")
        except ValueError:
            continue
    return date_str.strip()


def _format_atom_date(date_str):
    """Parse an Atom date string (ISO 8601) into a readable format."""
    if not date_str:
        return ""
    cleaned = date_str.strip()
    try:
        dt = datetime.fromisoformat(cleaned)
        return dt.strftime("%b %d, %Y")
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(cleaned[:19 if "T" in fmt else 10], fmt)
            return dt.strftime("%b %d, %Y")
        except ValueError:
            continue
    return cleaned


def build_blog_section(posts):
    """Build the markdown content for the blog section."""
    lines = ["### Latest Blog Posts", ""]
    for post in posts:
        date_part = f" — *{post['date']}*" if post["date"] else ""
        lines.append(f"- [{post['title']}]({post['link']}){date_part}")
    lines.append("")
    lines.append("[Read more ->](https://transscendsurvival.org/blog)")
    return "\n".join(lines)


# --- Section updater ---

def update_section(content, section_name, new_content):
    """Replace content between START_SECTION:<name> and END_SECTION:<name> markers."""
    pattern = rf"(<!--START_SECTION:{section_name}-->).*?(<!--END_SECTION:{section_name}-->)"
    replacement = rf"\1\n{new_content}\n\2"
    return re.sub(pattern, replacement, content, flags=re.DOTALL)


def main():
    if not GITHUB_TOKEN:
        print("Error: GITHUB_TOKEN not set")
        return

    repos = fetch_repos()
    included = [r for r in repos if should_include(r)]
    originals = [r for r in included if not r["isFork"]]

    print(f"Found {len(originals)} original repos (from {len(repos)} total)")

    with open(README_PATH, "r") as f:
        content = f.read()

    # Update activity section
    activity = build_activity_section(originals)
    content = update_section(content, "activity", activity)
    print(f"Updated activity: {originals[0]['name'] if originals else 'none'}")

    # Update repos section (original projects only, no forks)
    section_parts = []
    section_parts.append("")
    section_parts.append(build_original_table(originals))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    section_parts.append("")
    section_parts.append(f"*Last updated: {now}*")
    content = update_section(content, "repos", "\n".join(section_parts))
    print(f"Updated repos: {min(len(originals), MAX_ORIGINAL_REPOS)} shown")

    # Update blog section
    blog_posts = fetch_blog_posts()
    if blog_posts:
        blog_content = build_blog_section(blog_posts)
        content = update_section(content, "blog", blog_content)
        print(f"Updated blog section with {len(blog_posts)} posts")
    else:
        print("Skipping blog section update (no posts fetched)")

    with open(README_PATH, "w") as f:
        f.write(content)

    print("Done.")


if __name__ == "__main__":
    main()
