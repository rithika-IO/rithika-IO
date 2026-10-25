#!/usr/bin/env python3
"""Build the F1-themed profile panel for the profile README.

Run by .github/workflows/snake.yml after the snake has been generated.

Why this script exists
----------------------
An SVG shown in a README cannot load other images, so third-party stat cards
and the generated snake cannot simply be placed inside a themed box. This
script instead reads the numbers from the GitHub API, draws every section
itself, and stacks them inside ONE frame so the profile reads as a single
continuous panel:

    Driver card -> Car Setup -> The Garage -> Timing Tower -> Team Radio -> Race Track

Inputs
    GITHUB_TOKEN                  token for the GitHub API (provided by GitHub Actions)
    GH_USER                       GitHub login to read statistics for
    OUT_DIR                       folder holding github-snake-dark.svg; output goes here
    scripts/profile_content.json  name, intro, capabilities and tech stack entries (edit this to add a technology)
    assets/banner.png             banner picture shown in the intro

Output
    OUT_DIR/profile.svg

Only the Python standard library is used, so the workflow needs no install step.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import random
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LOGIN = os.environ.get("GH_USER", "rithika-IO")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUT_DIR = Path(os.environ.get("OUT_DIR", "dist"))
SNAKE_FILE = OUT_DIR / "github-snake-dark.svg"
CONTENT_FILE = Path(__file__).with_name("profile_content.json")

W = 1200            # panel width in SVG units
HEAD = 132          # height of each section's header strip
DIVIDER = 64        # vertical space taken by the flag divider between sections
SERIF = "'Hiragino Mincho ProN','Yu Mincho','Noto Serif CJK JP','Noto Serif JP','Songti SC',serif"
SANS = "'Segoe UI','Helvetica Neue',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"


# --------------------------------------------------------------------------
# GitHub API access
# --------------------------------------------------------------------------
def _request(url: str, payload: dict | None = None) -> dict:
    """Send one authenticated request and return the decoded JSON body."""
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Accept": "application/vnd.github+json", "User-Agent": f"{LOGIN}-profile-panels"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def graphql(query: str, **variables) -> dict:
    """Run a GraphQL query. Partial results are accepted; a response with no data is an error."""
    body = _request("https://api.github.com/graphql", {"query": query, "variables": variables})
    if body.get("errors"):
        print("GraphQL warnings:", json.dumps(body["errors"])[:500], file=sys.stderr)
    if not body.get("data"):
        raise RuntimeError("GitHub GraphQL API returned no data")
    return body["data"]


def fetch_contribution_days() -> dict[dt.date, int]:
    """Return {date: contribution count} for every day since the account's first active year."""
    years = graphql(
        "query($login:String!){user(login:$login){contributionsCollection{contributionYears}}}",
        login=LOGIN,
    )["user"]["contributionsCollection"]["contributionYears"]
    query = """
    query($login:String!,$from:DateTime!,$to:DateTime!){
      user(login:$login){
        contributionsCollection(from:$from,to:$to){
          contributionCalendar{weeks{contributionDays{date contributionCount}}}
        }
      }
    }"""
    days: dict[dt.date, int] = {}
    for year in years:
        cal = graphql(query, login=LOGIN, **{"from": f"{year}-01-01T00:00:00Z", "to": f"{year}-12-31T23:59:59Z"})
        for week in cal["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                days[dt.date.fromisoformat(day["date"])] = day["contributionCount"]
    return days


def compute_streaks(days: dict[dt.date, int], today: dt.date) -> dict:
    """Work out total contributions, the current streak and the longest streak.

    A day with no contributions ends a streak. Today is the one exception: an
    empty "today" does not end the current streak, because the day is not over.
    """
    past = sorted(d for d in days if d <= today)
    total = sum(days[d] for d in past)
    first = next((d for d in past if days[d] > 0), None)

    longest = {"length": 0, "start": None, "end": None}
    run_start, run_len = None, 0
    for d in past:
        if days[d] > 0:
            run_start = run_start or d
            run_len += 1
            if run_len > longest["length"]:
                longest = {"length": run_len, "start": run_start, "end": d}
        else:
            run_start, run_len = None, 0

    cursor = today if days.get(today, 0) > 0 else today - dt.timedelta(days=1)
    current = {"length": 0, "start": None, "end": None}
    while days.get(cursor, 0) > 0:
        current["length"] += 1
        current["start"] = cursor
        current["end"] = current["end"] or cursor
        cursor -= dt.timedelta(days=1)
    return {"total": total, "first": first, "current": current, "longest": longest}


# GitHub's own colours for common languages (the REST API does not return them).
LANGUAGE_COLOURS = {
    "TypeScript": "#3178C6", "JavaScript": "#F1E05A", "Java": "#B07219", "Python": "#3572A5",
    "C#": "#9B7BFF", "Go": "#00ADD8", "CSS": "#8E6FD8", "HTML": "#E34C26", "PHP": "#7A86B8",
    "Kotlin": "#A97BFF", "Rust": "#DEA584", "Swift": "#F05138", "Shell": "#89E051",
    "Dockerfile": "#5B8FA3", "EJS": "#D4427A", "Jupyter Notebook": "#DA5B0B", "SCSS": "#C6538C",
    "C++": "#F34B7D", "C": "#8A8A8A", "PLpgSQL": "#5B8FC7", "Makefile": "#6FA83A",
}


def rest(path: str) -> dict | list:
    """Call the GitHub REST API. Public data here is readable by the workflow token."""
    return _request("https://api.github.com" + path)


def search_count(kind: str, query: str) -> int:
    """Number of results for a search, for example all pull requests opened by the user."""
    return rest(f"/search/{kind}?per_page=1&q=" + urllib.parse.quote(query)).get("total_count", 0)


def fetch_stats() -> dict:
    """Return profile statistics and the most used languages.

    The REST API is used here on purpose. The token GitHub Actions provides is
    limited to the repository the workflow runs in, and the GraphQL API refuses
    to return details of the user's other repositories to it ("Resource not
    accessible by integration"). The REST API serves the same public data.
    """
    followers = rest(f"/users/{LOGIN}").get("followers", 0)

    repos, page = [], 1
    while True:
        batch = rest(f"/users/{LOGIN}/repos?type=owner&per_page=100&page={page}")
        repos += [r for r in batch if not r.get("fork")]
        if len(batch) < 100:
            break
        page += 1

    sizes: dict[str, int] = {}
    for repo in repos:
        for name, size in rest(f"/repos/{repo['full_name']}/languages").items():
            sizes[name] = sizes.get(name, 0) + size
    top = sorted(sizes.items(), key=lambda kv: kv[1], reverse=True)[:8]
    shown_total = sum(size for _, size in top) or 1
    languages = [{"name": name, "color": LANGUAGE_COLOURS.get(name, "#8B949E"), "percent": 100 * size / shown_total}
                 for name, size in top]

    # Optional extras. If the token may not read them, the panel still builds.
    reviews = contributed_to = 0
    try:
        extra = graphql(
            """
            query($login:String!){
              user(login:$login){
                contributionsCollection{totalPullRequestReviewContributions}
                repositoriesContributedTo(first:1,contributionTypes:[COMMIT,ISSUE,PULL_REQUEST,REPOSITORY]){totalCount}
              }
            }""",
            login=LOGIN,
        ).get("user") or {}
        reviews = (extra.get("contributionsCollection") or {}).get("totalPullRequestReviewContributions") or 0
        contributed_to = (extra.get("repositoriesContributedTo") or {}).get("totalCount") or 0
    except (RuntimeError, urllib.error.URLError, ValueError) as exc:
        print("Optional statistics unavailable:", exc, file=sys.stderr)

    return {
        "stars": sum(r.get("stargazers_count", 0) for r in repos),
        "commits": search_count("commits", f"author:{LOGIN}"),
        "prs": search_count("issues", f"author:{LOGIN} type:pr"),
        "issues": search_count("issues", f"author:{LOGIN} type:issue"),
        "contributed_to": contributed_to,
        "reviews": reviews,
        "followers": followers,
        "languages": languages,
    }


def rank(stats: dict) -> tuple[str, float]:
    """Grade the profile from S to C.

    Each figure is compared with a typical ("median") value and squashed into
    the range 0 to 1, then the results are combined with weights. This follows
    the public formula of the open-source github-readme-stats project, so the
    grade matches the card it replaces. Returns (grade, percentile); a lower
    percentile is better.
    """
    def exponential(x: float) -> float:
        return 1 - 2 ** -x

    def log_normal(x: float) -> float:
        return x / (1 + x)

    parts = [  # (weight, score)
        (2, exponential(stats["commits"] / 1000)),
        (3, exponential(stats["prs"] / 50)),
        (1, exponential(stats["issues"] / 25)),
        (1, exponential(stats["reviews"] / 2)),
        (4, log_normal(stats["stars"] / 50)),
        (1, log_normal(stats["followers"] / 10)),
    ]
    percentile = (1 - sum(w * s for w, s in parts) / sum(w for w, _ in parts)) * 100
    grades = [(1, "S"), (12.5, "A+"), (25, "A"), (37.5, "A-"), (50, "B+"), (62.5, "B"), (75, "B-"), (87.5, "C+"), (100, "C")]
    return next(g for limit, g in grades if percentile <= limit), percentile


# --------------------------------------------------------------------------
# Theme: neon F1 (Red Bull inspired colours, no logos or team names)
# --------------------------------------------------------------------------
NAVY0, NAVY1, NAVY2 = "#04061A", "#0B1440", "#130A3A"
RED, YEL, BLUE = "#FF1E56", "#FFE600", "#2F7BFF"
PURPLE, GREEN = "#B14BFF", "#2BFF88"          # F1 timing colours: fastest / personal best
WHITE, SOFT = "#FFFFFF", "#D7E0FF"
CARD = f'fill="#070B24" fill-opacity="0.88" stroke="{BLUE}" stroke-opacity="0.45" stroke-width="1.2"'


# --------------------------------------------------------------------------
# SVG drawing helpers
# --------------------------------------------------------------------------
def esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;")


def short(n: int) -> str:
    """1234 -> '1.2k'"""
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def text(x, y, content, size=16, fill=WHITE, weight=400, anchor="start", italic=False, glow=False) -> str:
    style = ' font-style="italic"' if italic else ""
    effect = ' filter="url(#glow)"' if glow else ""
    return (f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="{SANS}" font-weight="{weight}" '
            f'font-size="{size}" fill="{fill}"{style}{effect}>{esc(content)}</text>')


def fmt_date(day: dt.date | None, today: dt.date) -> str:
    """'Oct 5' for this year, 'Oct 21, 2025' for other years."""
    if day is None:
        return "-"
    label = f"{day:%b} {day.day}"
    return label if day.year == today.year else f"{label}, {day.year}"


def fmt_range(streak: dict, today: dt.date) -> str:
    if not streak["length"]:
        return "-"
    return f'{fmt_date(streak["start"], today)} - {fmt_date(streak["end"], today)}'


def speed_lines(seed: int, height: int) -> str:
    """Glowing streaks that race across the panel from left to right.

    A fixed seed keeps the pattern identical between runs, so the file only
    changes when the statistics change.
    """
    rng = random.Random(seed)
    out = []
    for _ in range(max(8, height // 140)):
        y = rng.uniform(20, height - 20)
        width = rng.uniform(140, 340)
        colour = rng.choice([YEL, BLUE, RED, BLUE, WHITE])
        dur = rng.uniform(1.2, 2.6)
        out.append(
            f'<rect x="-400" y="{y:.0f}" width="{width:.0f}" height="2" rx="1" fill="{colour}" opacity="{rng.uniform(0.35, 0.85):.2f}" filter="url(#glow)">'
            f'<animate attributeName="x" from="-400" to="{W + 50}" dur="{dur:.1f}s" begin="-{rng.uniform(0, dur):.1f}s" repeatCount="indefinite"/></rect>')
    return "\n    ".join(out)


def checkered(x: float, y: float, columns: int, size: int = 12, rows: int = 2) -> str:
    return "".join(f'<rect x="{x + c * size}" y="{y + r * size}" width="{size}" height="{size}" fill="{WHITE}"/>'
                   for c in range(columns) for r in range(rows) if (c + r) % 2 == 0)


def section_header(label: str, title: str, ghost: str) -> str:
    """Header strip: small yellow label, big italic title with a red and yellow stripe."""
    title_w = len(title) * 33
    return f'''<text x="{W - 40}" y="118" text-anchor="end" font-family="{SANS}" font-style="italic" font-weight="900" font-size="120" fill="none" stroke="{BLUE}" stroke-opacity="0.22" stroke-width="2">{esc(ghost)}</text>
    <g transform="translate(40,46) skewX(-14)"><rect width="16" height="58" fill="{RED}" filter="url(#glow)"/><rect x="22" width="6" height="58" fill="{YEL}" filter="url(#glow)"/></g>
    {text(92, 58, label, 13, YEL, 800, glow=True).replace("<text ", '<text letter-spacing="5" ')}
    {text(90, 100, title, 40, WHITE, 900, italic=True, glow=True).replace("<text ", '<text letter-spacing="2" ')}
    <rect x="92" y="112" width="{title_w}" height="4" fill="{RED}" filter="url(#glow)"/><rect x="{92 + title_w + 4}" y="112" width="60" height="4" fill="{YEL}" filter="url(#glow)"/>
    <rect x="40" y="{HEAD}" width="{W - 80}" height="1.5" fill="{BLUE}" opacity="0.35"/>'''


def flag_divider(y: float) -> str:
    """Divider between sections: glowing red and yellow lines meeting at a small chequered flag."""
    return f'''<g transform="translate(0,{y})">
      <rect x="60" y="-1" width="490" height="2" fill="url(#lineL)" filter="url(#glow)"/><rect x="650" y="-1" width="490" height="2" fill="url(#lineR)" filter="url(#glow)"/>
      <g transform="translate(564,-12) skewX(-12)">{checkered(0, 0, 6, 12)}<rect width="72" height="24" fill="none" stroke="{WHITE}" stroke-opacity="0.6"/></g>
    </g>'''


def pill_width(item: dict, padding: int) -> int:
    """Width of a chip: fixed padding plus the label width (measured, or estimated for new entries)."""
    return padding + item.get("text_width", round(len(item["label"]) * 9.2))


# --------------------------------------------------------------------------
# Section bodies. Each returns (svg, height) with y measured from the section top.
# --------------------------------------------------------------------------
def hero_body(profile: dict, today: dt.date) -> tuple[str, int]:
    """Driver card: number, name, roles, banner picture and the intro paragraph.

    An SVG shown as an image cannot load a separate picture file, so the banner
    is read from the repository and embedded as text (a base64 "data URI").
    """
    banner = Path(__file__).resolve().parent.parent / profile["banner"]
    encoded = base64.b64encode(banner.read_bytes()).decode()
    number = str(profile["race_number"])
    bw = W - 160
    bh = round(bw * profile["banner_height"] / profile["banner_width"])
    by = 214
    roles = f'</tspan><tspan fill="{YEL}" dx="10">/</tspan><tspan dx="10">'.join(esc(r) for r in profile["roles"])
    parts = [
        checkered(0, 0, 100),
        f'<text x="{W - 30}" y="204" text-anchor="end" font-family="{SANS}" font-style="italic" font-weight="900" font-size="230" fill="none" stroke="{BLUE}" stroke-opacity="0.35" stroke-width="2" filter="url(#glow)">{number}</text>',
        text(58, 70, f"DRIVER PROFILE · SEASON {today.year}", 14, YEL, 800, glow=True).replace("<text ", '<text letter-spacing="5" '),
        f'<g transform="translate(58,86) skewX(-12)"><rect width="112" height="78" rx="4" fill="{RED}" filter="url(#glow)"/>'
        f'<text x="56" y="62" text-anchor="middle" font-family="{SANS}" font-weight="900" font-size="62" fill="{WHITE}">{number}</text></g>',
        text(196, 142, profile["name"], 56, WHITE, 900, italic=True, glow=True).replace("<text ", '<text letter-spacing="2" '),
        f'<rect x="196" y="156" width="400" height="4" fill="{RED}" filter="url(#glow)"/><rect x="600" y="156" width="80" height="4" fill="{YEL}" filter="url(#glow)"/>',
        f'<text x="196" y="190" font-family="{SANS}" font-weight="700" font-size="18" fill="{WHITE}"><tspan>{roles}</tspan></text>',
        f'<image x="80" y="{by}" width="{bw}" height="{bh}" preserveAspectRatio="xMidYMid meet" href="data:image/png;base64,{encoded}"/>',
        f'<rect x="60" y="{by + bh + 22}" width="{W - 120}" height="1.5" fill="{BLUE}" opacity="0.5"/>',
    ]
    ty = by + bh + 62
    for i, line in enumerate(profile["intro_lines"]):
        parts.append(text(600, ty + i * 29, line, 18, SOFT, 400, "middle"))
    return "\n    ".join(parts), ty + (len(profile["intro_lines"]) - 1) * 29 + 40


def capabilities_body(items: list[dict]) -> tuple[str, int]:
    chip_h, gap, parts, y = 42, 12, [], HEAD + 38
    half = (len(items) + 1) // 2
    for row in (items[:half], items[half:]):
        widths = [pill_width(i, 16 + 12 + 10 + 18) for i in row]
        x = (W - sum(widths) - gap * (len(row) - 1)) / 2
        for item, w in zip(row, widths):
            colour = RED if items.index(item) % 2 == 0 else YEL
            parts.append(
                f'<g transform="translate({x:.1f},{y})"><rect width="{w}" height="{chip_h}" rx="6" {CARD}/>'
                f'<g transform="translate(16,{chip_h / 2 - 8}) skewX(-14)"><rect width="5" height="16" fill="{colour}" filter="url(#glow)"/><rect x="8" width="3" height="16" fill="{colour}" opacity="0.6"/></g>'
                f'<text x="38" y="{chip_h / 2 + 5.5}" font-family="{SANS}" font-weight="600" font-size="16" fill="{WHITE}" '
                f'textLength="{w - 56}" lengthAdjust="spacingAndGlyphs">{esc(item["label"])}</text></g>')
            x += w + gap
        y += chip_h + 16
    return "\n    ".join(parts), y - 16 + 36


def tech_stack_body(categories: list[dict]) -> tuple[str, int]:
    pill_h, pad_l, icon, gap, pad_r, between = 40, 13, 18, 9, 15, 10
    parts, y = [], HEAD + 46
    for cat in categories:
        title = cat["category"].upper()
        tw = len(title) * 13.6
        parts.append(
            f'<rect x="{600 - tw / 2 - 190:.0f}" y="{y - 6}" width="170" height="2" fill="url(#lineL)"/>'
            f'<rect x="{600 + tw / 2 + 20:.0f}" y="{y - 6}" width="170" height="2" fill="url(#lineR)"/>'
            f'<text x="600" y="{y}" text-anchor="middle" font-family="{SANS}" font-style="italic" font-weight="800" font-size="17" letter-spacing="3" fill="{WHITE}">{esc(title)}</text>')
        y += 22
        widths = [pill_width(i, pad_l + icon + gap + pad_r) for i in cat["items"]]
        x = (W - sum(widths) - between * (len(widths) - 1)) / 2
        for item, w in zip(cat["items"], widths):
            colour = item.get("colour", BLUE)
            if item.get("icon"):
                mark = f'<path d="{item["icon"]}" fill="{colour}" transform="translate({pad_l},{(pill_h - icon) / 2}) scale({icon / 24})"/>'
            else:
                c = pad_l + icon / 2
                mark = f'<rect x="{c - 5.5}" y="{pill_h / 2 - 5.5}" width="11" height="11" rx="2" fill="{colour}" transform="rotate(45 {c} {pill_h / 2})"/>'
            parts.append(
                f'<g transform="translate({x:.1f},{y})"><rect width="{w}" height="{pill_h}" rx="6" {CARD}/>'
                f'<rect x="6" y="{pill_h - 2.2}" width="{w - 12}" height="1.6" rx="0.8" fill="{colour}" opacity="0.7"/>{mark}'
                f'<text x="{pad_l + icon + gap}" y="{pill_h / 2 + 5.5}" font-family="{SANS}" font-weight="600" font-size="16" fill="{WHITE}" '
                f'textLength="{w - pad_l - icon - gap - pad_r}" lengthAdjust="spacingAndGlyphs">{esc(item["label"])}</text></g>')
            x += w + between
        y += pill_h + 50
    return "\n    ".join(parts), y - 50 + 36


def metrics_body(streaks: dict, stats: dict, today: dt.date) -> tuple[str, int]:
    parts: list[str] = []

    # --- timing strip: three cells, coloured like F1 sector times -----------
    cx, cy, cw, ch = 140, HEAD + 30, 920, 170
    cells = [
        ("TOTAL CONTRIBUTIONS", f'{streaks["total"]:,}', f'{fmt_date(streaks["first"], today)} - Present', YEL, "LAPS"),
        ("CURRENT STREAK", f'{streaks["current"]["length"]} days', fmt_range(streaks["current"], today), GREEN, "PERSONAL BEST"),
        ("LONGEST STREAK", f'{streaks["longest"]["length"]} days', fmt_range(streaks["longest"], today), PURPLE, "FASTEST"),
    ]
    cell_w = (cw - 2 * 14) / 3
    for i, (label, value, sub, colour, tag) in enumerate(cells):
        x = cx + i * (cell_w + 14)
        parts += [
            f'<rect x="{x:.1f}" y="{cy}" width="{cell_w:.1f}" height="{ch}" rx="8" {CARD}/>',
            f'<rect x="{x:.1f}" y="{cy}" width="{cell_w:.1f}" height="5" rx="2" fill="{colour}" filter="url(#glow)"/>',
            f'<g transform="translate({x + 22:.1f},{cy + 24}) skewX(-12)"><rect width="{len(tag) * 9 + 18}" height="22" rx="3" fill="{colour}"/>'
            f'<text x="{(len(tag) * 9 + 18) / 2}" y="16" text-anchor="middle" font-family="{SANS}" font-weight="900" font-size="12" letter-spacing="1.5" fill="{NAVY0}">{tag}</text></g>',
            text(x + cell_w / 2, cy + 104, value, 40, WHITE, 900, "middle", italic=True, glow=True),
            text(x + cell_w / 2, cy + 132, label, 14, colour, 800, "middle").replace("<text ", '<text letter-spacing="2" '),
            text(x + cell_w / 2, cy + 154, sub, 14, SOFT, 400, "middle"),
        ]

    # --- driver stats card -------------------------------------------------
    px, py, pw, ph = 100, cy + ch + 24, 580, 236
    grade, percentile = rank(stats)
    ring_r = 48
    circumference = 2 * 3.14159265 * ring_r
    filled = circumference * (100 - percentile) / 100
    parts.append(f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" rx="10" {CARD}/>')
    parts.append(text(px + 28, py + 46, "DRIVER STATS · POWER LEVEL", 19, YEL, 900, italic=True, glow=True))
    rows = [("Total Stars Earned", stats["stars"]), ("Total Commits", stats["commits"]), ("Total PRs", stats["prs"]),
            ("Total Issues", stats["issues"]), ("Contributed to (last year)", stats["contributed_to"])]
    for i, (label, value) in enumerate(rows):
        ry = py + 88 + i * 30
        parts.append(f'<g transform="translate({px + 28},{ry - 13}) skewX(-14)"><rect width="5" height="15" fill="{RED}"/></g>')
        parts.append(text(px + 46, ry, label, 16, WHITE, 700))
        parts.append(text(px + 330, ry, short(value), 16, WHITE, 800))
    rcx, rcy = px + 470, py + 138
    parts += [
        f'<circle cx="{rcx}" cy="{rcy}" r="{ring_r}" fill="none" stroke="#1A2558" stroke-width="7"/>',
        f'<circle cx="{rcx}" cy="{rcy}" r="{ring_r}" fill="none" stroke="{RED}" stroke-width="7" stroke-linecap="round" filter="url(#glow)" '
        f'stroke-dasharray="{filled:.1f} {circumference:.1f}" transform="rotate(-90 {rcx} {rcy})"/>',
        text(rcx, rcy + 11, grade, 32, WHITE, 900, "middle", italic=True),
    ]

    # --- power unit (languages) card ---------------------------------------
    lx, lw = px + pw + 20, 400
    parts.append(f'<rect x="{lx}" y="{py}" width="{lw}" height="{ph}" rx="10" {CARD}/>')
    parts.append(text(lx + 28, py + 46, "POWER UNIT · LANGUAGES", 19, YEL, 900, italic=True, glow=True))
    bar_w, offset, segments = 344, 0.0, []
    for lang in stats["languages"]:
        seg = bar_w * lang["percent"] / 100
        segments.append(f'<rect x="{offset:.1f}" y="0" width="{seg:.1f}" height="10" fill="{lang["color"]}"/>')
        offset += seg
    parts.append(f'<g transform="translate({lx + 28},{py + 68})" clip-path="url(#langbar)">{"".join(segments)}</g>')
    half = (len(stats["languages"]) + 1) // 2
    for i, lang in enumerate(stats["languages"]):
        col, row = divmod(i, half)
        tx, ty = lx + 28 + col * 178, py + 116 + row * 30
        parts.append(f'<circle cx="{tx + 6}" cy="{ty - 5}" r="6" fill="{lang["color"]}"/>')
        parts.append(text(tx + 20, ty, f'{lang["name"]} {lang["percent"]:.2f}%', 15, WHITE, 500))

    return "\n    ".join(parts), py + ph + 36


def radio_body(messages: list[str]) -> tuple[str, int]:
    """Pit-wall radio card. Each message fades in for a few seconds, then the next one."""
    hold = 4                                   # seconds each message stays on screen
    cycle = hold * len(messages)
    x, y, w, h = 140, HEAD + 30, 920, 150
    share = 1 / len(messages)
    parts = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" {CARD}/>',
        f'<rect x="{x}" y="{y}" width="6" height="{h}" rx="3" fill="{RED}" filter="url(#glow)"/>',
        text(x + 34, y + 36, "RACE ENGINEER", 13, YEL, 800, glow=True).replace("<text ", '<text letter-spacing="4" '),
        f'<circle cx="{x + w - 40}" cy="{y + 31}" r="6" fill="{RED}" filter="url(#glow)"><animate attributeName="opacity" values="1;0.2;1" dur="1.2s" repeatCount="indefinite"/></circle>',
        text(x + w - 54, y + 36, "LIVE", 13, RED, 900, "end").replace("<text ", '<text letter-spacing="3" '),
    ]
    # animated waveform bars
    rng = random.Random(33)
    for i in range(28):
        bx = x + 34 + i * 9
        high = rng.uniform(10, 34)
        parts.append(
            f'<rect x="{bx}" y="{y + 118 - 4}" width="5" height="4" rx="1.5" fill="{BLUE}" opacity="0.85" filter="url(#glow)">'
            f'<animate attributeName="height" values="4;{high:.0f};6;{high * 0.6:.0f};4" dur="{rng.uniform(0.8, 1.6):.1f}s" repeatCount="indefinite"/>'
            f'<animate attributeName="y" values="{y + 114};{y + 118 - high:.0f};{y + 112};{y + 118 - high * 0.6:.0f};{y + 114}" dur="{rng.uniform(0.8, 1.6):.1f}s" repeatCount="indefinite"/></rect>')
    for i, message in enumerate(messages):
        parts.append(
            f'<g opacity="0">{text(x + 34, y + 84, "“" + message + "”", 26, WHITE, 800, italic=True, glow=True)}'
            f'<animate attributeName="opacity" values="0;1;1;0;0" keyTimes="0;{share * 0.08:.3f};{share * 0.9:.3f};{share:.3f};1" '
            f'dur="{cycle}s" begin="{i * hold}s;{i * hold}s+{cycle}s" repeatCount="indefinite"/></g>')
    return "\n    ".join(parts), y + h + 36


def track_body(snake_svg: str) -> tuple[str, int]:
    """Place the generated snake (the 'car') under its header, with a start/finish line.

    The snake file is itself an SVG, and one SVG may contain another, so its
    contents are copied in as a nested <svg> element and scaled to fit.
    """
    root = re.search(r"<svg\b[^>]*>", snake_svg)
    view = re.search(r'viewBox="([^"]+)"', root.group(0)) if root else None
    if not root or not view:
        raise RuntimeError("Snake file is not in the expected SVG format")
    _, _, vw, vh = (float(v) for v in view.group(1).split())
    inner = snake_svg[root.end(): snake_svg.rindex("</svg>")]
    width = W - 120
    snake_h = round(width * vh / vw)
    top = HEAD + 22
    flag = f'<g transform="translate(46,{top + 10})">{checkered(0, 0, 1, 10, rows=int(snake_h / 10) - 2)}{checkered(10, 10, 1, 10, rows=int(snake_h / 10) - 3)}</g>'
    return f'{flag}<svg x="80" y="{top}" width="{width}" height="{snake_h}" viewBox="{view.group(1)}">{inner}</svg>', top + snake_h + 30


CAR_BODY, CAR_TYRE = "#1B2A6B", "#111111"


def car_shape(scale: float = 1.0, body: str = CAR_BODY) -> str:
    """Top-down F1 car pointing right (+x), centred on its middle, about 120 x 48 units before scaling."""
    t = lambda x, y, w, h: f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="{CAR_TYRE}" stroke="#555" stroke-width="1"/>'
    return f'''<g transform="scale({scale})">
  <g transform="translate(-60,0)">
    <!-- rear wing -->
    <rect x="0" y="-22" width="12" height="44" rx="2" fill="{RED}"/><rect x="2" y="-22" width="3" height="44" fill="{YEL}"/>
    <!-- rear tyres -->
    {t(14,-26,24,13)}{t(14,13,24,13)}
    <!-- floor / sidepods -->
    <path d="M10,-9 L30,-16 L62,-17 L74,-9 L74,9 L62,17 L30,16 L10,9 Z" fill="{body}"/>
    <path d="M34,-16 L60,-16 L60,-12 L34,-11 Z M34,16 L60,16 L60,12 L34,11 Z" fill="{RED}"/>
    <!-- nose -->
    <path d="M60,-7 L104,-4 L114,0 L104,4 L60,7 Z" fill="{body}"/>
    <path d="M70,-2 L110,-1 L114,0 L110,1 L70,2 Z" fill="{RED}"/>
    <path d="M106,-3 L114,0 L106,3 Z" fill="{YEL}"/>
    <!-- engine cover and cockpit -->
    <path d="M14,-5 L52,-8 L52,8 L14,5 Z" fill="#24357F"/>
    <ellipse cx="58" cy="0" rx="10" ry="6" fill="#05081C"/>
    <circle cx="56" cy="0" r="4.2" fill="{YEL}"/>
    <path d="M48,-7 Q62,-9 68,0 Q62,9 48,7" fill="none" stroke="#9AA6C8" stroke-width="2"/>
    <text x="30" y="4" font-family="Arial,Helvetica,sans-serif" font-weight="900" font-style="italic" font-size="11" fill="{WHITE}">33</text>
    <!-- suspension arms -->
    <path d="M78,-6 L84,-16 M78,6 L84,16 M30,-9 L26,-14 M30,9 L26,14" stroke="#9AA6C8" stroke-width="1.6"/>
    <!-- front tyres -->
    {t(76,-27,20,12)}{t(76,15,20,12)}
    <!-- front wing -->
    <path d="M108,-24 L118,-22 L118,22 L108,24 Z" fill="{RED}"/><rect x="112" y="-22" width="3" height="44" fill="{YEL}"/>
  </g></g>'''


def race_cars(height: int) -> str:
    """Two small F1 cars racing each other down the panel along a zigzag line.

    The racing line is a sine wave that sweeps across the full width while it
    moves down. It is stored as one <path>, and <animateMotion> drives each car
    along it; rotate="auto" turns the car to face its direction of travel.

    Both cars finish the run at the same moment, but keyPoints/keyTimes give
    them a different pace in each part of the run, so they keep overtaking
    each other. The second car follows a line shifted down slightly, like a
    parallel lane, so they pass side by side instead of through each other.
    """
    import math
    top, bottom, amplitude, wavelength = 40, height - 40, (W - 140) / 2, 520
    centre = W / 2

    def line(shift: float) -> str:
        points = []
        for y in range(top, bottom + 1, 8):
            x = centre + amplitude * math.sin(2 * math.pi * (y - top) / wavelength)
            points.append(f"{x:.1f},{y + shift}")
        return "M" + " L".join(points)

    length = sum(2 * amplitude * 4 for _ in range(int((bottom - top) / wavelength) + 1))
    run = round(length / 700)                               # about 700 px per second
    cars = [  # (path id, lane shift, body colour, pace)
        ("lineA", 0, CAR_BODY, "0;0.30;0.48;0.78;1"),
        ("lineB", 26, BLUE, "0;0.24;0.55;0.72;1"),
    ]
    out = []
    for path_id, shift, body, pace in cars:
        out.append(f'''<path id="{path_id}" d="{line(shift)}" fill="none" stroke="none"/>
    <g>
      <rect x="-48" y="-1.5" width="36" height="3" rx="1.5" fill="url(#trail)" filter="url(#glow)"/>
      {car_shape(0.24, body)}
      <animateMotion dur="{run}s" repeatCount="indefinite" rotate="auto" calcMode="linear"
        keyPoints="{pace}" keyTimes="0;0.25;0.5;0.75;1"><mpath href="#{path_id}"/></animateMotion>
    </g>''')
    return "\n    ".join(out)


# --------------------------------------------------------------------------
# Whole panel
# --------------------------------------------------------------------------
def build_profile(content: dict, streaks: dict, stats: dict, snake_svg: str, today: dt.date) -> str:
    """Stack the driver card and every section in one frame, with a flag divider between them."""
    sections = [  # (label, title, ghost word, (body svg, body height))
        ("CORE CAPABILITIES", "CAR SETUP", "SETUP", capabilities_body(content["capabilities"])),
        ("TECH STACK", "THE GARAGE", "GARAGE", tech_stack_body(content["tech_stack"])),
        ("METRICS", "TIMING TOWER", "TIMING", metrics_body(streaks, stats, today)),
        ("PIT WALL", "TEAM RADIO", "RADIO", radio_body(content["radio_messages"])),
        ("CONTRIBUTION ACTIVITY", "RACE TRACK", "TRACK", track_body(snake_svg)),
    ]
    hero, hero_height = hero_body(content["profile"], today)
    blocks = [f"<g>\n    {hero}\n    </g>", flag_divider(hero_height + DIVIDER / 2)]
    y = hero_height + DIVIDER
    for position, (label, title, ghost, (body, height)) in enumerate(sections, start=1):
        blocks.append(f'<g transform="translate(0,{y})">\n    {section_header(label, title, ghost)}\n    {body}\n    </g>')
        y += height
        if position < len(sections):
            blocks.append(flag_divider(y + DIVIDER / 2))
            y += DIVIDER
    height = y + 24

    profile = content["profile"]
    grade, _ = rank(stats)
    label = (
        f'{profile["name"].title()}, number {profile["race_number"]}. {" | ".join(profile["roles"])}. {" ".join(profile["intro_lines"])} '
        + "Core capabilities: " + ", ".join(i["label"] for i in content["capabilities"]) + ". "
        + "Tech stack: " + " ".join(f'{c["category"]}: {", ".join(i["label"] for i in c["items"])}.' for c in content["tech_stack"])
        + f' Metrics: {streaks["total"]} total contributions, current streak {streaks["current"]["length"]} days, '
        f'longest streak {streaks["longest"]["length"]} days, power level {grade}. '
        "Team radio: " + " ".join(content["radio_messages"]) + " "
        "Contribution activity: animated snake eating the contribution graph."
    )
    joined = "\n    ".join(blocks)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height}" width="{W}" height="{height}" role="img" aria-label="{esc(label)}">
  <title>{esc(label)}</title>
  <style>@media (prefers-reduced-motion: reduce) {{ .fx {{ display: none; }} }}</style>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{NAVY0}"/><stop offset="0.6" stop-color="{NAVY1}"/><stop offset="1" stop-color="{NAVY2}"/></linearGradient>
    <linearGradient id="lineL" x1="0" x2="1"><stop offset="0" stop-color="{RED}" stop-opacity="0"/><stop offset="1" stop-color="{RED}"/></linearGradient>
    <linearGradient id="lineR" x1="0" x2="1"><stop offset="0" stop-color="{YEL}"/><stop offset="1" stop-color="{YEL}" stop-opacity="0"/></linearGradient>
    <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40,0 H0 V40" fill="none" stroke="{BLUE}" stroke-opacity="0.12"/></pattern>
    <clipPath id="clip"><rect x="1" y="1" width="{W - 2}" height="{height - 2}" rx="14"/></clipPath>
    <clipPath id="langbar"><rect x="0" y="0" width="344" height="10" rx="5"/></clipPath>
    <linearGradient id="trail" x1="0" x2="1"><stop offset="0" stop-color="{YEL}" stop-opacity="0"/><stop offset="1" stop-color="{YEL}" stop-opacity="0.9"/></linearGradient>
    <filter id="glow" x="-30%" y="-200%" width="160%" height="500%"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  </defs>
  <g clip-path="url(#clip)">
    <rect width="{W}" height="{height}" fill="url(#bg)"/>
    <rect width="{W}" height="{height}" fill="url(#grid)"/>
    <g class="fx">
    {speed_lines(33, height)}
    </g>
    {joined}
    {race_cars(height)}
    <polygon points="0,{height} 520,{height} 556,{height - 18} 0,{height - 18}" fill="{RED}" filter="url(#glow)"/>
    <polygon points="562,{height - 18} 586,{height - 18} 550,{height} 526,{height}" fill="{YEL}" filter="url(#glow)"/>
  </g>
  <rect x="1" y="1" width="{W - 2}" height="{height - 2}" rx="14" fill="none" stroke="{BLUE}" stroke-width="2" filter="url(#glow)"/>
</svg>
'''


def main() -> None:
    if not TOKEN:
        sys.exit("GITHUB_TOKEN is not set")
    if not SNAKE_FILE.exists():
        sys.exit(f"{SNAKE_FILE} not found; the snake must be generated before this script runs")
    content = json.loads(CONTENT_FILE.read_text(encoding="utf-8"))
    today = dt.datetime.now(dt.timezone.utc).date()
    streaks = compute_streaks(fetch_contribution_days(), today)
    stats = fetch_stats()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    svg = build_profile(content, streaks, stats, SNAKE_FILE.read_text(encoding="utf-8"), today)
    (OUT_DIR / "profile.svg").write_text(svg, encoding="utf-8")
    print(f'Wrote {OUT_DIR}/profile.svg (total {streaks["total"]}, '
          f'current streak {streaks["current"]["length"]}, grade {rank(stats)[0]})')


if __name__ == "__main__":
    main()
