#!/usr/bin/env python3
"""Shared utilities for the profile README pipeline.

Pure functions, frozen dataclasses, and config loading. No side effects.
"""

import json
import os
import subprocess
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import reduce


def pipe(initial, *fns):
    """Compose functions left-to-right, threading an initial value."""
    return reduce(lambda acc, fn: fn(acc), fns, initial)


# --- Frozen dataclasses ---


@dataclass(frozen=True)
class Repo:
    name: str
    description: str
    url: str
    primary_language: str
    languages: list = field(default_factory=list)  # [(name, size, color)]
    topics: list = field(default_factory=list)
    stars: int = 0
    is_fork: bool = False
    pushed_at: str = ""
    parent: str = ""
    total_lang_size: int = 0


@dataclass(frozen=True)
class CategorizedRepo:
    repo: Repo
    category: str


@dataclass(frozen=True)
class FossContribution:
    name: str
    name_with_owner: str
    url: str
    description: str
    primary_language: str
    languages: list = field(default_factory=list)  # [(name, size, color)]
    stars: int = 0


@dataclass(frozen=True)
class BlogPost:
    title: str
    link: str
    date: str


@dataclass(frozen=True)
class CategoryConfig:
    name: str
    match_topics: list = field(default_factory=list)
    match_languages: list = field(default_factory=list)
    match_repos: list = field(default_factory=list)
    weight: int = 1


@dataclass(frozen=True)
class PipelineConfig:
    user: str
    blog_feed_url: str
    blog_post_count: int
    max_repos: int
    blocklist: list = field(default_factory=list)
    orgs: list = field(default_factory=list)
    org_exclusions_for_foss: list = field(default_factory=list)
    category_order: list = field(default_factory=list)
    categories: list = field(default_factory=list)  # [CategoryConfig]
    stats: dict = field(default_factory=dict)


# --- Config loading ---


def load_config(path=None):
    """Load pipeline config from JSON file."""
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "config.json")
    with open(path) as f:
        raw = json.load(f)
    cats = [
        CategoryConfig(
            name=c["name"],
            match_topics=c.get("match_topics", []),
            match_languages=c.get("match_languages", []),
            match_repos=c.get("match_repos", []),
            weight=c.get("weight", 1),
        )
        for c in raw.get("categories", [])
    ]
    return PipelineConfig(
        user=raw["user"],
        blog_feed_url=raw["blog_feed_url"],
        blog_post_count=raw.get("blog_post_count", 3),
        max_repos=raw.get("max_repos", 0),
        blocklist=raw.get("blocklist", []),
        orgs=raw.get("orgs", []),
        org_exclusions_for_foss=raw.get("org_exclusions_for_foss", []),
        category_order=raw.get("category_order", []),
        categories=cats,
        stats=raw.get("stats", {}),
    )


# --- GraphQL ---


def graphql_request(token, query):
    """Execute a GraphQL query. Tries urllib first, falls back to gh CLI."""
    url = "https://api.github.com/graphql"
    data = None
    if token:
        try:
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "profile-readme-updater",
            }
            payload = json.dumps({"query": query}).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers=headers)
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            print(f"urllib failed ({exc}), trying gh cli...")

    if data is None:
        result = subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={query}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"gh api failed: {result.stderr}")
        data = json.loads(result.stdout)

    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data


# --- XML/text helpers ---


def escape_xml(text):
    """Escape special XML characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


# --- Repo parsing ---


def parse_repo(node):
    """Convert a raw GraphQL repo node to a frozen Repo."""
    primary = node.get("primaryLanguage")
    langs = [
        (e["node"]["name"], e.get("size", 0), e["node"].get("color", ""))
        for e in node.get("languages", {}).get("edges", [])
    ]
    topics = [
        n["topic"]["name"]
        for n in node.get("repositoryTopics", {}).get("nodes", [])
    ]
    parent = node.get("parent")
    return Repo(
        name=node["name"],
        description=node.get("description") or "",
        url=node["url"],
        primary_language=primary["name"] if primary else "",
        languages=langs,
        topics=topics,
        stars=node.get("stargazerCount", 0),
        is_fork=node.get("isFork", False),
        pushed_at=node.get("pushedAt", ""),
        parent=parent["nameWithOwner"] if parent else "",
        total_lang_size=node.get("languages", {}).get("totalSize", 0),
    )


# --- Categorization ---


def categorize_repo(repo, config):
    """Assign a category using weighted scoring against config rules.

    Score = (topic_hits * weight) + (lang_match * weight * 0.5) + (repo_name_match * weight * 100)
    Highest score wins. All-zero falls to "Other".
    """
    repo_topics_lower = {t.lower() for t in repo.topics}
    best_cat = "Other"
    best_score = 0.0

    for cat in config.categories:
        if cat.name == "Other":
            continue
        score = 0.0
        # Hard repo name match
        if repo.name in cat.match_repos:
            score += cat.weight * 100
        # Topic matches
        topic_hits = sum(
            1 for t in cat.match_topics if t.lower() in repo_topics_lower
        )
        score += topic_hits * cat.weight
        # Language match
        if repo.primary_language in cat.match_languages:
            score += cat.weight * 0.5

        if score > best_score:
            best_score = score
            best_cat = cat.name

    return CategorizedRepo(repo=repo, category=best_cat)


# --- Date formatters ---


def format_iso_date(date_str):
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
            return dt.strftime("%b %Y")
    except (ValueError, TypeError):
        return date_str[:10]


def format_rss_date(date_str):
    """Parse an RSS pubDate string into a readable format."""
    if not date_str:
        return ""
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime("%b %d, %Y")
        except ValueError:
            continue
    return date_str.strip()


def format_atom_date(date_str):
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
            dt = datetime.strptime(cleaned[: 19 if "T" in fmt else 10], fmt)
            return dt.strftime("%b %d, %Y")
        except ValueError:
            continue
    return cleaned
