#!/usr/bin/env python3
"""Update the profile README with latest repo data from GitHub GraphQL API.

Uses only stdlib + urllib (no pip installs needed).
"""

import json
import os
import re
import urllib.request
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


def update_section(content, new_content):
    """Replace content between START_SECTION:repos and END_SECTION:repos markers."""
    pattern = r"(<!--START_SECTION:repos-->).*?(<!--END_SECTION:repos-->)"
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

    content = update_section(content, section_content)

    with open(README_PATH, "w") as f:
        f.write(content)

    print(f"Updated README with {len(originals)} original repos and {len(forks)} forks")


if __name__ == "__main__":
    main()
