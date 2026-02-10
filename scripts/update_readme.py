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

# Repos to exclude (test/trivial/profile)
BLOCKLIST = {
    "test",
    "testing",
    "test-repo",
    "hello-world",
    "Jesssullivan",
}

QUERY = """
{
  user(login: "Jesssullivan") {
    repositories(first: 100, orderBy: {field: PUSHED_AT, direction: DESC}, privacy: PUBLIC) {
      nodes {
        name
        description
        url
        primaryLanguage { name }
        stargazerCount
        isFork
        parent { nameWithOwner }
      }
    }
  }
}
"""


def fetch_repos():
    """Fetch public repos via GitHub GraphQL API using urllib."""
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


def build_original_table(repos):
    """Build markdown table for non-fork (original) repos."""
    lines = ["| Repo | Description | Lang |", "|------|-------------|------|"]
    for repo in repos:
        name = repo["name"]
        desc = (repo["description"] or "").replace("|", "\\|")
        lang = repo.get("primaryLanguage")
        lang_name = lang["name"] if lang else ""
        url = repo["url"]
        lines.append(f"| [{name}]({url}) | {desc} | {lang_name} |")
    return "\n".join(lines)


def build_forks_table(repos):
    """Build markdown table for forked repos with star badges."""
    lines = ["| Fork | What |", "|------|------|"]
    for repo in repos:
        name = repo["name"]
        desc = (repo["description"] or "").replace("|", "\\|")
        badge = f"![](https://img.shields.io/github/stars/Jesssullivan/{name}?style=social&label={name})"
        lines.append(f"| {badge} | {desc} |")
    return "\n".join(lines)


BLOG_FEED_URL = "https://jesssullivan.github.io/feed.xml"
BLOG_POST_COUNT = 3


def fetch_blog_posts():
    """Fetch the latest blog posts from the RSS feed.

    Returns a list of dicts with 'title', 'link', and 'date' keys,
    or an empty list if the feed is unreachable or unparseable.
    """
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
    entries = root.findall("atom:entry", ns)
    if not entries:
        entries = root.findall("entry")
    for entry in entries[:BLOG_POST_COUNT]:
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
    lines.append("[Read more ->](https://jesssullivan.github.io/blog)")
    return "\n".join(lines)


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
    forks = [r for r in included if r["isFork"]]

    print(f"Found {len(originals)} original repos, {len(forks)} forks")

    # Build the combined section content
    section_parts = []

    # Original Projects table
    section_parts.append("")
    section_parts.append(build_original_table(originals))
    section_parts.append("")

    # FOSS Contributions heading + table
    section_parts.append("### FOSS Contributions")
    section_parts.append("")
    section_parts.append(build_forks_table(forks))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    section_parts.append("")
    section_parts.append(f"*Last updated: {now}*")

    section_content = "\n".join(section_parts)

    with open(README_PATH, "r") as f:
        content = f.read()

    content = update_section(content, "repos", section_content)

    # Update blog section (gracefully skipped if feed is unavailable)
    blog_posts = fetch_blog_posts()
    if blog_posts:
        blog_content = build_blog_section(blog_posts)
        content = update_section(content, "blog", blog_content)
        print(f"Updated blog section with {len(blog_posts)} posts")
    else:
        print("Skipping blog section update (no posts fetched)")

    with open(README_PATH, "w") as f:
        f.write(content)

    print(f"Updated README with {len(originals)} original repos and {len(forks)} forks")


if __name__ == "__main__":
    main()
