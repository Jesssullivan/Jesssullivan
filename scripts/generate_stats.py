#!/usr/bin/env python3
"""Generate GitHub stats and top languages SVG cards.

Reads repos_data.json for star counts and language byte sizes.
Fetches contribution stats via GitHub GraphQL API.
Outputs github-stats.svg, github-stats-dark.svg, top-langs.svg, top-langs-dark.svg.

Uses only stdlib — no pip installs needed.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from shared import escape_xml, graphql_request, load_config

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUT_DIR = os.path.dirname(os.path.dirname(__file__))

# Octicon SVG paths (16x16 viewBox)
ICON_STAR = "M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.75.75 0 0 1-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Z"
ICON_COMMIT = "M11.93 8.5a4.002 4.002 0 0 1-7.86 0H.75a.75.75 0 0 1 0-1.5h3.32a4.002 4.002 0 0 1 7.86 0h3.32a.75.75 0 0 1 0 1.5Zm-1.43-.5a2.5 2.5 0 1 0-5 0 2.5 2.5 0 0 0 5 0Z"
ICON_PR = "M1.5 3.25a2.25 2.25 0 1 1 3 2.122v5.256a2.251 2.251 0 1 1-1.5 0V5.372A2.25 2.25 0 0 1 1.5 3.25Zm5.677-.177L9.573.677A.25.25 0 0 1 10 .854V2.5h1A2.5 2.5 0 0 1 13.5 5v5.628a2.251 2.251 0 1 1-1.5 0V5a1 1 0 0 0-1-1h-1v1.646a.25.25 0 0 1-.427.177L7.177 3.427a.25.25 0 0 1 0-.354ZM3.75 2.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm0 9.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm8.25.75a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0Z"
ICON_ISSUE = "M8 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM1.5 8a6.5 6.5 0 1 0 13 0 6.5 6.5 0 0 0-13 0Z"
ICON_CONTRIB = "M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1 0-1.5h1.75v-2h-8a1 1 0 0 0-.714 1.7.75.75 0 1 1-1.072 1.05A2.495 2.495 0 0 1 2 11.5Zm10.5-1h-8a1 1 0 0 0-1 1v6.708A2.486 2.486 0 0 1 4.5 9h8ZM5 12.25a.25.25 0 0 1 .25-.25h3.5a.25.25 0 0 1 .25.25v3.25a.25.25 0 0 1-.4.2l-1.45-1.087a.249.249 0 0 0-.3 0L5.4 15.7a.25.25 0 0 1-.4-.2Z"

# Theme palettes
THEMES = {
    "light": {
        "bg": "#fffefe",
        "title": "#2f80ed",
        "text": "#434d58",
        "icon": "#4c71f2",
        "border": "#e4e2e2",
    },
    "dark": {
        "bg": "#141321",
        "title": "#fe428e",
        "text": "#a9fef7",
        "icon": "#f8d847",
        "border": "#e4e2e2",
    },
}

# Fallback language colors
LANG_COLORS = {
    "Python": "#3572A5",
    "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6",
    "Go": "#00ADD8",
    "Rust": "#dea584",
    "Shell": "#89e051",
    "Haskell": "#5e5086",
    "Chapel": "#8dc63f",
    "C++": "#f34b7d",
    "C": "#555555",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "R": "#198CE7",
    "Nix": "#7e7eff",
    "HCL": "#844FBA",
    "Zig": "#ec915c",
    "Svelte": "#ff3e00",
    "Emacs Lisp": "#c065db",
    "Dockerfile": "#384d54",
    "Jinja": "#a52a22",
    "Makefile": "#427819",
    "Jupyter Notebook": "#DA5B0B",
    "Java": "#b07219",
    "Ruby": "#701516",
    "Futhark": "#5f021f",
    "Starlark": "#76d275",
    "Just": "#384d54",
    "RouterOS Script": "#DE3941",
    "Cython": "#fedf5b",
}

CONTRIB_QUERY_TEMPLATE = """
{{
  user(login: "{user}") {{
    contributionsCollection {{
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalRepositoryContributions
      contributionCalendar {{ totalContributions }}
    }}
    repositoriesContributedTo(first: 1, contributionTypes: [COMMIT, ISSUE, PULL_REQUEST, REPOSITORY]) {{
      totalCount
    }}
    pullRequests(first: 1) {{ totalCount }}
    openIssues: issues(states: OPEN) {{ totalCount }}
    closedIssues: issues(states: CLOSED) {{ totalCount }}
  }}
}}
"""


def fetch_contribution_stats(user, foss_count=None):
    """Fetch contribution stats from GitHub GraphQL API."""
    query = CONTRIB_QUERY_TEMPLATE.format(user=user)
    data = graphql_request(GITHUB_TOKEN, query)
    user = data["data"]["user"]
    cc = user["contributionsCollection"]
    contributed_to = foss_count if foss_count is not None else user["repositoriesContributedTo"]["totalCount"]
    return {
        "contributions": cc["contributionCalendar"]["totalContributions"],
        "commits": cc["totalCommitContributions"],
        "prs": user["pullRequests"]["totalCount"],
        "issues": user["openIssues"]["totalCount"] + user["closedIssues"]["totalCount"],
        "contributed_to": contributed_to,
    }


def compute_total_stars(repos):
    """Sum stargazerCount across all repos."""
    return sum(r.get("stargazerCount", 0) for r in repos)


def compute_language_stats(repos):
    """Aggregate language byte sizes across all repos. Returns sorted list of (name, bytes, color)."""
    lang_bytes = {}
    lang_colors = {}
    for repo in repos:
        langs = repo.get("languages", {})
        for edge in langs.get("edges", []):
            name = edge["node"]["name"]
            size = edge.get("size", 0)
            color = edge["node"].get("color")
            lang_bytes[name] = lang_bytes.get(name, 0) + size
            if color and name not in lang_colors:
                lang_colors[name] = color

    # Sort by byte count descending
    sorted_langs = sorted(lang_bytes.items(), key=lambda x: x[1], reverse=True)
    result = []
    for name, size in sorted_langs:
        color = lang_colors.get(name) or LANG_COLORS.get(name, "#8b8b8b")
        result.append((name, size, color))
    return result


def render_stats_svg(stats, theme_name):
    """Render the GitHub stats card as SVG."""
    t = THEMES[theme_name]
    w, h = 450, 220

    rows = [
        ("Stars Earned", str(stats["stars"]), ICON_STAR),
        ("Contributions (this year)", f"{stats['contributions']:,}", ICON_COMMIT),
        ("Commits (this year)", f"{stats['commits']:,}", ICON_COMMIT),
        ("Total PRs", str(stats["prs"]), ICON_PR),
        ("Total Issues", str(stats["issues"]), ICON_ISSUE),
        ("Contributed to (FOSS)", str(stats["contributed_to"]), ICON_CONTRIB),
    ]

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
        f'  <style>',
        f'    .title {{ font: 600 18px "Segoe UI", Ubuntu, Sans-Serif; fill: {t["title"]}; }}',
        f'    .stat {{ font: 600 14px "Segoe UI", Ubuntu, Sans-Serif; fill: {t["text"]}; }}',
        f'    .label {{ font: 400 14px "Segoe UI", Ubuntu, Sans-Serif; fill: {t["text"]}; }}',
        f'  </style>',
        f'  <rect x="0.5" y="0.5" rx="4.5" width="{w - 1}" height="{h - 1}" fill="{t["bg"]}" stroke="{t["border"]}" />',
        f'  <text x="25" y="35" class="title" fill="{t["title"]}" font-size="18" font-weight="600" font-family="\'Segoe UI\', Ubuntu, Sans-Serif">Jess Sullivan&#x27;s GitHub Stats</text>',
    ]

    y_start = 60
    line_height = 25
    for i, (label, value, icon_path) in enumerate(rows):
        y = y_start + i * line_height
        # Icon
        lines.append(
            f'  <g transform="translate(25, {y - 12})">'
            f'<svg width="16" height="16" viewBox="0 0 16 16">'
            f'<path fill="{t["icon"]}" d="{icon_path}"/>'
            f'</svg></g>'
        )
        # Label
        lines.append(
            f'  <text x="50" y="{y}" class="label" fill="{t["text"]}" font-size="14" font-family="\'Segoe UI\', Ubuntu, Sans-Serif">{escape_xml(label)}:</text>'
        )
        # Value (right-aligned)
        lines.append(
            f'  <text x="{w - 25}" y="{y}" class="stat" text-anchor="end" fill="{t["text"]}" font-size="14" font-weight="600" font-family="\'Segoe UI\', Ubuntu, Sans-Serif">{escape_xml(value)}</text>'
        )

    lines.append("</svg>")
    return "\n".join(lines)


def render_langs_svg(lang_stats, theme_name):
    """Render the top languages card as SVG with compact bar layout."""
    t = THEMES[theme_name]
    w = 300
    top_n = 8
    langs = lang_stats[:top_n]

    if not langs:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="50"><text x="10" y="30">No language data</text></svg>'

    total_bytes = sum(size for _, size, _ in langs)

    # Compute percentages
    lang_pcts = []
    for name, size, color in langs:
        pct = (size / total_bytes * 100) if total_bytes > 0 else 0
        lang_pcts.append((name, pct, color))

    # Layout constants
    bar_y = 50
    bar_h = 8
    bar_margin_x = 25
    bar_w = w - 2 * bar_margin_x
    label_start_y = bar_y + bar_h + 24
    label_line_h = 20
    cols = 2
    col_w = (w - 2 * bar_margin_x) // cols

    # Compute card height
    rows_needed = (len(lang_pcts) + cols - 1) // cols
    h = label_start_y + rows_needed * label_line_h + 15

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
        f'  <style>',
        f'    .title {{ font: 600 18px "Segoe UI", Ubuntu, Sans-Serif; fill: {t["title"]}; }}',
        f'    .lang-name {{ font: 400 11px "Segoe UI", Ubuntu, Sans-Serif; fill: {t["text"]}; }}',
        f'  </style>',
        f'  <rect x="0.5" y="0.5" rx="4.5" width="{w - 1}" height="{h - 1}" fill="{t["bg"]}" stroke="{t["border"]}" />',
        f'  <text x="25" y="33" class="title" fill="{t["title"]}" font-size="18" font-weight="600" font-family="\'Segoe UI\', Ubuntu, Sans-Serif">Most Used Languages</text>',
    ]

    # Stacked bar with mask for rounded corners
    lines.append(f'  <defs>')
    lines.append(f'    <clipPath id="bar-clip">')
    lines.append(f'      <rect x="{bar_margin_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="5" />')
    lines.append(f'    </clipPath>')
    lines.append(f'  </defs>')
    lines.append(f'  <g clip-path="url(#bar-clip)">')

    x_offset = bar_margin_x
    for name, pct, color in lang_pcts:
        seg_w = max(1, bar_w * pct / 100)
        lines.append(
            f'    <rect x="{x_offset:.1f}" y="{bar_y}" width="{seg_w:.1f}" height="{bar_h}" fill="{color}" />'
        )
        x_offset += seg_w

    lines.append(f'  </g>')

    # Language labels in two columns
    for i, (name, pct, color) in enumerate(lang_pcts):
        col = i % cols
        row = i // cols
        x = bar_margin_x + col * col_w
        y = label_start_y + row * label_line_h

        # Colored circle
        lines.append(
            f'  <circle cx="{x + 5}" cy="{y - 4}" r="5" fill="{color}" />'
        )
        # Label text
        pct_str = f"{pct:.1f}%" if pct >= 0.1 else "<0.1%"
        lines.append(
            f'  <text x="{x + 15}" y="{y}" class="lang-name" fill="{t["text"]}" font-size="11" font-family="\'Segoe UI\', Ubuntu, Sans-Serif">{escape_xml(name)} {pct_str}</text>'
        )

    lines.append("</svg>")
    return "\n".join(lines)


def compute_language_stats_with_foss(repos, foss_repos):
    """Aggregate language bytes from both own repos and FOSS contributions."""
    lang_bytes = {}
    lang_colors = {}
    for repo_list in [repos, foss_repos]:
        for repo in repo_list:
            langs = repo.get("languages", {})
            for edge in langs.get("edges", []):
                name = edge["node"]["name"]
                size = edge.get("size", 0)
                color = edge["node"].get("color")
                lang_bytes[name] = lang_bytes.get(name, 0) + size
                if color and name not in lang_colors:
                    lang_colors[name] = color

    sorted_langs = sorted(lang_bytes.items(), key=lambda x: x[1], reverse=True)
    result = []
    for name, size in sorted_langs:
        color = lang_colors.get(name) or LANG_COLORS.get(name, "#8b8b8b")
        result.append((name, size, color))
    return result


def main():
    config = load_config()

    # Load repo data
    repos_path = os.path.join(OUT_DIR, "repos_data.json")
    if not os.path.exists(repos_path):
        print(f"Error: {repos_path} not found. Run update_readme.py first.", file=sys.stderr)
        sys.exit(1)

    with open(repos_path) as f:
        repos = json.load(f)

    print(f"Loaded {len(repos)} repos from repos_data.json")

    # Load FOSS data if available
    foss_path = os.path.join(OUT_DIR, "foss_data.json")
    foss_repos = []
    if os.path.exists(foss_path):
        with open(foss_path) as f:
            foss_repos = json.load(f)
        print(f"Loaded {len(foss_repos)} FOSS contributions from foss_data.json")

    # Load org repo data if available
    org_path = os.path.join(OUT_DIR, "org_repos_data.json")
    org_repos = []
    if os.path.exists(org_path):
        with open(org_path) as f:
            org_repos = json.load(f)
        print(f"Loaded {len(org_repos)} org repos from org_repos_data.json")

    # Fetch contribution stats, using FOSS data count for consistency
    print("Fetching contribution stats...")
    foss_count = len(foss_repos) if foss_repos else None
    contrib = fetch_contribution_stats(config.user, foss_count=foss_count)

    # Stars from personal repos only
    total_stars = compute_total_stars(repos)

    stats = {
        "stars": total_stars,
        "contributions": contrib["contributions"],
        "commits": contrib["commits"],
        "prs": contrib["prs"],
        "issues": contrib["issues"],
        "contributed_to": contrib["contributed_to"],
    }
    print(f"Stats: {stats}")

    # Compute language stats — merge sources based on config
    lang_source = list(repos)  # always start with personal repos
    include_org = config.stats.get("include_org_in_lang_stats", False)
    include_foss = config.stats.get("include_foss_in_lang_stats", False)
    if include_org and org_repos:
        lang_source = lang_source + org_repos
        print(f"Including {len(org_repos)} org repos in language stats")
    if include_foss and foss_repos:
        lang_source = lang_source + foss_repos
        print(f"Including {len(foss_repos)} FOSS repos in language stats")
    lang_stats = compute_language_stats(lang_source)
    print(f"Languages: {len(lang_stats)} total, top 8: {[l[0] for l in lang_stats[:8]]}")

    # Generate stats cards
    for theme, suffix in [("light", ""), ("dark", "-dark")]:
        svg = render_stats_svg(stats, theme)
        path = os.path.join(OUT_DIR, f"github-stats{suffix}.svg")
        with open(path, "w") as f:
            f.write(svg)
        print(f"Wrote {path}")

    # Generate language cards
    for theme, suffix in [("light", ""), ("dark", "-dark")]:
        svg = render_langs_svg(lang_stats, theme)
        path = os.path.join(OUT_DIR, f"top-langs{suffix}.svg")
        with open(path, "w") as f:
            f.write(svg)
        print(f"Wrote {path}")

    print("Done generating stats SVGs.")


if __name__ == "__main__":
    main()
