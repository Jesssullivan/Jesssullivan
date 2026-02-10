#!/usr/bin/env python3
"""Generate SVG repo relationship graphs (light & dark) from repo JSON data.

Reads repo data from repos_data.json (or stdin / /tmp fallback), computes Jaccard
similarity on topics + languages, then uses networkx spring_layout for
force-directed positioning. Outputs repo-graph.svg and repo-graph-dark.svg.
Also generates a Mermaid graph definition at repo-graph.mmd.
"""

import json
import math
import sys
import os
import random

import networkx as nx

# Category color palette
CATEGORY_COLORS = {
    "Languages & Compilers": "#e74c3c",
    "Infrastructure & DevOps": "#3498db",
    "Hardware & Maker": "#e67e22",
    "ML & Data": "#2ecc71",
    "ML & Ecology": "#2ecc71",  # alias
    "Web & Apps": "#9b59b6",
    "Other": "#7f8c8d",
}

# Import category mappings from update_readme
sys.path.insert(0, os.path.dirname(__file__))
from update_readme import REPO_CATEGORIES, LANG_CATEGORY

SVG_WIDTH = 960
SVG_HEIGHT = 600
MARGIN = 50
FOOTER_HEIGHT = 50  # reserved for info text
NODE_MIN_R = 5
NODE_MAX_R = 16
SIMILARITY_THRESHOLD = 0.15
FONT_SIZE = 12
FONT_SIZE_SMALL = 9
LABEL_CHAR_WIDTH = 7.2  # approx width per char at font-size 12
LEGEND_WIDTH = 155
LEGEND_HEIGHT = 120


def categorize_repo(repo):
    """Assign a category to a repo."""
    name = repo["name"]
    if name in REPO_CATEGORIES:
        return REPO_CATEGORIES[name]
    lang = repo.get("primaryLanguage")
    lang_name = lang["name"] if lang else ""
    if lang_name in LANG_CATEGORY:
        return LANG_CATEGORY[lang_name]
    return "Other"


def get_tags(repo):
    """Get the set of topics + languages for a repo."""
    tags = set()
    for edge in repo.get("languages", {}).get("edges", []):
        tags.add(edge["node"]["name"].lower())
    primary = repo.get("primaryLanguage")
    if primary:
        tags.add(primary["name"].lower())
    for node in repo.get("repositoryTopics", {}).get("nodes", []):
        tags.add(node["topic"]["name"].lower())
    return tags


def jaccard_similarity(set_a, set_b):
    """Compute Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def escape_xml(text):
    """Escape special XML characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def generate_graph(repos):
    """Build the networkx graph and compute layout."""
    repo_tags = {}
    for repo in repos:
        repo_tags[repo["name"]] = get_tags(repo)

    G = nx.Graph()
    for repo in repos:
        name = repo["name"]
        category = categorize_repo(repo)
        tag_count = len(repo_tags[name])
        radius = min(NODE_MAX_R, max(NODE_MIN_R, NODE_MIN_R + (tag_count - 1) * 0.9))
        G.add_node(name, category=category, radius=radius, tag_count=tag_count)

    names = [r["name"] for r in repos]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            sim = jaccard_similarity(repo_tags[names[i]], repo_tags[names[j]])
            if sim > SIMILARITY_THRESHOLD:
                G.add_edge(names[i], names[j], weight=sim)

    random.seed(42)
    if len(G.nodes) == 0:
        return G, {}

    # Higher k = more spread, more iterations for convergence
    pos = nx.spring_layout(
        G,
        k=5.0 / math.sqrt(max(len(G.nodes), 1)),
        iterations=300,
        seed=42,
        scale=1.0,
    )

    # Scale positions to SVG coordinates — use FULL canvas width
    plot_w = SVG_WIDTH - 2 * MARGIN
    plot_h = SVG_HEIGHT - 2 * MARGIN - FOOTER_HEIGHT

    if pos:
        xs = [p[0] for p in pos.values()]
        ys = [p[1] for p in pos.values()]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        range_x = max_x - min_x if max_x != min_x else 1
        range_y = max_y - min_y if max_y != min_y else 1

        scaled_pos = {}
        for name, (x, y) in pos.items():
            sx = MARGIN + ((x - min_x) / range_x) * plot_w
            sy = MARGIN + ((y - min_y) / range_y) * plot_h
            scaled_pos[name] = (sx, sy)
    else:
        scaled_pos = {}

    return G, scaled_pos


def resolve_label_positions(scaled_pos, G):
    """Compute label positions with iterative nudging to reduce overlap."""
    labels = {}
    for name, (cx, cy) in scaled_pos.items():
        radius = G.nodes[name]["radius"]
        # Place label to right by default, left if too far right
        if cx > SVG_WIDTH - MARGIN - 120:
            lx = cx - radius - 3
            anchor = "end"
        else:
            lx = cx + radius + 3
            anchor = "start"
        ly = cy + FONT_SIZE * 0.35
        labels[name] = (lx, ly, anchor)

    # Iterative nudging: push overlapping labels apart vertically
    label_list = list(labels.keys())
    for _ in range(50):
        moved = False
        for i in range(len(label_list)):
            for j in range(i + 1, len(label_list)):
                n1, n2 = label_list[i], label_list[j]
                x1, y1, a1 = labels[n1]
                x2, y2, a2 = labels[n2]

                w1 = len(n1) * LABEL_CHAR_WIDTH
                w2 = len(n2) * LABEL_CHAR_WIDTH
                h = FONT_SIZE + 2

                if a1 == "start":
                    left1, right1 = x1, x1 + w1
                else:
                    left1, right1 = x1 - w1, x1
                if a2 == "start":
                    left2, right2 = x2, x2 + w2
                else:
                    left2, right2 = x2 - w2, x2

                x_overlap = left1 < right2 and left2 < right1
                y_overlap = abs(y1 - y2) < h

                if x_overlap and y_overlap:
                    nudge = (h - abs(y1 - y2)) / 2 + 1.5
                    if y1 <= y2:
                        labels[n1] = (x1, y1 - nudge, a1)
                        labels[n2] = (x2, y2 + nudge, a2)
                    else:
                        labels[n1] = (x1, y1 + nudge, a1)
                        labels[n2] = (x2, y2 - nudge, a2)
                    moved = True
        if not moved:
            break

    return labels


def render_svg(G, scaled_pos, dark=False):
    """Render the graph as an SVG string."""
    if dark:
        bg_color = "#0d1117"
        text_color = "#e6edf3"
        text_muted = "#8b949e"
        edge_color = "#6e7681"
        legend_bg = "#161b22"
        legend_border = "#30363d"
        footer_color = "#484f58"
        eq_color = "#8b949e"
    else:
        bg_color = "#ffffff"
        text_color = "#1f2328"
        text_muted = "#656d76"
        edge_color = "#bcc3cd"
        legend_bg = "#f6f8fa"
        legend_border = "#d0d7de"
        footer_color = "#d0d7de"
        eq_color = "#656d76"

    label_positions = resolve_label_positions(scaled_pos, G)

    lines = []
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{SVG_WIDTH}" height="{SVG_HEIGHT}" '
        f'viewBox="0 0 {SVG_WIDTH} {SVG_HEIGHT}">'
    )
    lines.append(
        f'  <rect width="{SVG_WIDTH}" height="{SVG_HEIGHT}" fill="{bg_color}" rx="8" />'
    )

    # Title
    lines.append(
        f'  <text x="{SVG_WIDTH // 2}" y="24" font-family="system-ui, -apple-system, sans-serif" '
        f'font-size="13" fill="{text_muted}" text-anchor="middle" font-weight="500">'
        f'Repo Relationship Graph &#x2014; Pairwise Topic &amp; Language Similarity</text>'
    )

    # Footer separator line
    footer_y = SVG_HEIGHT - FOOTER_HEIGHT
    lines.append(
        f'  <line x1="{MARGIN}" y1="{footer_y}" x2="{SVG_WIDTH - MARGIN}" y2="{footer_y}" '
        f'stroke="{footer_color}" stroke-width="0.5" opacity="0.5" />'
    )

    # Footer info
    eq_y1 = footer_y + 20
    eq_y2 = footer_y + 38
    lines.append(
        f'  <text x="{MARGIN}" y="{eq_y1}" font-family="system-ui, -apple-system, sans-serif" '
        f'font-size="9" fill="{text_muted}" opacity="0.6">'
        f'Updated daily by GitHub Actions</text>'
    )
    lines.append(
        f'  <text x="{MARGIN}" y="{eq_y2}" font-family="system-ui, -apple-system, sans-serif" '
        f'font-size="9" fill="{text_muted}" opacity="0.6">'
        f'networkx spring_layout \u00b7 Jaccard similarity &gt; 0.15</text>'
    )

    # Node + edge count (right-aligned)
    lines.append(
        f'  <text x="{SVG_WIDTH - MARGIN}" y="{eq_y1}" font-family="system-ui, -apple-system, sans-serif" '
        f'font-size="9" fill="{text_muted}" text-anchor="end" opacity="0.6">'
        f'{len(G.nodes)} repos \u00b7 {len(G.edges)} edges</text>'
    )

    # Edges
    for u, v, data in G.edges(data=True):
        if u in scaled_pos and v in scaled_pos:
            x1, y1 = scaled_pos[u]
            x2, y2 = scaled_pos[v]
            sim = data.get("weight", 0.2)
            opacity = min(0.8, max(0.15, sim * 1.1))
            stroke_w = 0.6 + sim * 1.8
            lines.append(
                f'  <line x1="{x1:.1f}" y1="{y1:.1f}" '
                f'x2="{x2:.1f}" y2="{y2:.1f}" '
                f'stroke="{edge_color}" stroke-width="{stroke_w:.1f}" '
                f'opacity="{opacity:.2f}" />'
            )

    # Nodes
    for name in G.nodes:
        if name not in scaled_pos:
            continue
        cx, cy = scaled_pos[name]
        cat = G.nodes[name]["category"]
        r = G.nodes[name]["radius"]
        color = CATEGORY_COLORS.get(cat, CATEGORY_COLORS["Other"])
        if dark:
            # Glow effect
            lines.append(
                f'  <circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r + 4}" '
                f'fill="{color}" opacity="0.12" />'
            )
        lines.append(
            f'  <circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" '
            f'fill="{color}" opacity="0.88" />'
        )

    # Labels with background for legibility
    for name in G.nodes:
        if name not in label_positions:
            continue
        lx, ly, anchor = label_positions[name]
        escaped = escape_xml(name)
        text_w = len(name) * LABEL_CHAR_WIDTH
        # Text background rect for readability
        if anchor == "start":
            rx = lx - 1
        else:
            rx = lx - text_w - 1
        ry = ly - FONT_SIZE + 1
        lines.append(
            f'  <rect x="{rx:.1f}" y="{ry:.1f}" width="{text_w + 2:.1f}" '
            f'height="{FONT_SIZE + 3}" fill="{bg_color}" opacity="0.75" rx="2" />'
        )
        lines.append(
            f'  <text x="{lx:.1f}" y="{ly:.1f}" '
            f'font-family="system-ui, -apple-system, sans-serif" '
            f'font-size="{FONT_SIZE}" fill="{text_color}" '
            f'text-anchor="{anchor}">{escaped}</text>'
        )

    # Legend — overlay in top-right
    legend_x = SVG_WIDTH - LEGEND_WIDTH - 12
    legend_y = 36
    lines.append(
        f'  <rect x="{legend_x}" y="{legend_y}" '
        f'width="{LEGEND_WIDTH}" height="{LEGEND_HEIGHT}" '
        f'rx="6" fill="{legend_bg}" stroke="{legend_border}" '
        f'stroke-width="1" opacity="0.95" />'
    )

    legend_cats = [
        ("Languages & Compilers", "#e74c3c"),
        ("Infrastructure & DevOps", "#3498db"),
        ("Hardware & Maker", "#e67e22"),
        ("ML & Data", "#2ecc71"),
        ("Web & Apps", "#9b59b6"),
        ("Other", "#7f8c8d"),
    ]
    for i, (cat_name, cat_color) in enumerate(legend_cats):
        ey = legend_y + 16 + i * 17
        ex = legend_x + 12
        lines.append(
            f'  <circle cx="{ex + 5}" cy="{ey}" r="5" '
            f'fill="{cat_color}" opacity="0.88" />'
        )
        lines.append(
            f'  <text x="{ex + 15}" y="{ey + 4}" '
            f'font-family="system-ui, -apple-system, sans-serif" '
            f'font-size="10" fill="{text_color}">{escape_xml(cat_name)}</text>'
        )

    # Node + edge count in legend footer
    lines.append(
        f'  <text x="{legend_x + LEGEND_WIDTH // 2}" y="{legend_y + LEGEND_HEIGHT - 6}" '
        f'font-family="system-ui, -apple-system, sans-serif" '
        f'font-size="8" fill="{text_muted}" text-anchor="middle">'
        f'{len(G.nodes)} repos \u00b7 {len(G.edges)} edges</text>'
    )

    lines.append("</svg>")
    return "\n".join(lines)


def generate_mermaid(G):
    """Generate a Mermaid graph definition for textual examination."""
    lines = ["graph LR"]

    # Add nodes with category styling
    cat_styles = {
        "Languages & Compilers": "fill:#e74c3c,color:#fff",
        "Infrastructure & DevOps": "fill:#3498db,color:#fff",
        "Hardware & Maker": "fill:#e67e22,color:#fff",
        "ML & Data": "fill:#2ecc71,color:#fff",
        "Web & Apps": "fill:#9b59b6,color:#fff",
        "Other": "fill:#7f8c8d,color:#fff",
    }

    # Sanitize node names for Mermaid (replace hyphens, dots)
    def mermaid_id(name):
        return name.replace("-", "_").replace(".", "_").replace(" ", "_")

    # Add edges (only strong ones to keep readable)
    strong_edges = [(u, v, d) for u, v, d in G.edges(data=True) if d.get("weight", 0) > 0.25]
    for u, v, data in strong_edges:
        w = data.get("weight", 0)
        label = f"{w:.0%}"
        lines.append(f"    {mermaid_id(u)}[\"{u}\"] ---|{label}| {mermaid_id(v)}[\"{v}\"]")

    # Add isolated nodes
    connected = set()
    for u, v, _ in strong_edges:
        connected.add(u)
        connected.add(v)
    for name in G.nodes:
        if name not in connected:
            lines.append(f"    {mermaid_id(name)}[\"{name}\"]")

    # Style classes
    lines.append("")
    for cat, style in cat_styles.items():
        class_name = cat.replace(" & ", "_").replace(" ", "_").lower()
        members = [mermaid_id(n) for n in G.nodes if G.nodes[n].get("category") == cat]
        if members:
            lines.append(f"    classDef {class_name} {style}")
            lines.append(f"    class {','.join(members)} {class_name}")

    return "\n".join(lines)


def main():
    data_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "repos_data.json")
    tmp_path = "/tmp/repos_data.json"

    if os.path.exists(data_path):
        with open(data_path) as f:
            repos = json.load(f)
    elif not sys.stdin.isatty():
        repos = json.load(sys.stdin)
    elif os.path.exists(tmp_path):
        with open(tmp_path) as f:
            repos = json.load(f)
    else:
        print("Error: no repo data found. Pipe JSON via stdin or provide repos_data.json", file=sys.stderr)
        sys.exit(1)

    print(f"Generating graph for {len(repos)} repos...")

    G, pos = generate_graph(repos)
    print(f"Graph: {len(G.nodes)} nodes, {len(G.edges)} edges")

    out_dir = os.path.dirname(os.path.dirname(__file__))

    light_svg = render_svg(G, pos, dark=False)
    light_path = os.path.join(out_dir, "repo-graph.svg")
    with open(light_path, "w") as f:
        f.write(light_svg)
    print(f"Wrote {light_path}")

    dark_svg = render_svg(G, pos, dark=True)
    dark_path = os.path.join(out_dir, "repo-graph-dark.svg")
    with open(dark_path, "w") as f:
        f.write(dark_svg)
    print(f"Wrote {dark_path}")

    # Generate Mermaid definition
    mermaid = generate_mermaid(G)
    mermaid_path = os.path.join(out_dir, "repo-graph.mmd")
    with open(mermaid_path, "w") as f:
        f.write(mermaid)
    print(f"Wrote {mermaid_path}")


if __name__ == "__main__":
    main()
