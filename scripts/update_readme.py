#!/usr/bin/env python3
"""Update the profile README with latest repo data from GitHub GraphQL API."""

import json
import os
import re
from datetime import datetime, timezone

import requests

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GRAPHQL_URL = "https://api.github.com/graphql"
README_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "README.md")

# Repos to exclude from the dynamic listing
EXCLUDE_REPOS = {
    "Jesssullivan",  # profile repo itself
    "jesssullivan.github.io",  # blog
}

# Repos to always show (showcase)
SHOWCASE_REPOS = [
    "quickchpl",
    "GloriousFlywheel",
    "XoxdWM",
    "RemoteJuggler",
    "gnucashr",
    "pixelwise-research",
    "MerlinAI-Interpreters",
    "Arduino_Coil_Winder",
    "clipi",
    "mo-image-identifier",
    "Ansible-DAG-Harness",
]

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
        forkCount
        pushedAt
        isFork
      }
    }
  }
}
"""


def fetch_repos():
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Content-Type": "application/json",
    }
    resp = requests.post(GRAPHQL_URL, json={"query": QUERY}, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    return data["data"]["user"]["repositories"]["nodes"]


def format_repo_table(repos):
    lines = ["| Repo | Description | Lang |", "|------|-------------|------|"]
    for repo in repos:
        name = repo["name"]
        if name in EXCLUDE_REPOS:
            continue
        desc = (repo["description"] or "").replace("|", "\\|")
        lang = repo.get("primaryLanguage", {})
        lang_name = lang["name"] if lang else ""
        url = repo["url"]
        lines.append(f"| [{name}]({url}) | {desc} | {lang_name} |")
    return "\n".join(lines)


def update_section(content, section_name, new_content):
    pattern = rf"(<!--START_SECTION:{section_name}-->).*?(<!--END_SECTION:{section_name}-->)"
    replacement = rf"\1\n{new_content}\n\2"
    return re.sub(pattern, replacement, content, flags=re.DOTALL)


def main():
    if not GITHUB_TOKEN:
        print("GITHUB_TOKEN not set, skipping update")
        return

    repos = fetch_repos()
    showcase = [r for r in repos if r["name"] in SHOWCASE_REPOS and not r["isFork"]]
    # Sort showcase by the predefined order
    showcase.sort(key=lambda r: SHOWCASE_REPOS.index(r["name"]) if r["name"] in SHOWCASE_REPOS else 999)

    table = format_repo_table(showcase)

    with open(README_PATH, "r") as f:
        content = f.read()

    content = update_section(content, "repos", table)

    with open(README_PATH, "w") as f:
        f.write(content)

    print(f"Updated README with {len(showcase)} showcase repos")


if __name__ == "__main__":
    main()
