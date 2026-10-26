#!/usr/bin/env python3
"""Build the F1 poster profile for the profile README.

Run by .github/workflows/snake.yml after the snake has been generated.

Why this script exists
----------------------
An SVG shown in a README cannot load other images, so third-party stat cards
and the generated snake cannot simply be placed inside a themed box. This
script instead reads the numbers from the GitHub API, draws every section
itself, and stacks them inside ONE frame so the profile reads as a single
continuous panel:

    Poster -> Driver Bio -> Sector Times -> Speed Trace -> Timing Tower -> Tyre Strategy
    -> Drivers' Championship (live F1 data) -> Team Radio -> Race Track

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
# Theme: F1 poster (light editorial poster + F1 data graphics)
# --------------------------------------------------------------------------
# Colours: Red Bull palette (colours only; no logos or team names are drawn)
PAPER, PAPER2, INK, MUTED, RULE = "#ECEBE7", "#E2E0DA", "#111111", "#6B6B6B", "#C9C7C1"
NAVY, RED, YELLOW, BLUE, CAN = "#233268", "#DB0B44", "#FFD200", "#1D19AF", "#F4ECEF"
WHITE = "#FFFFFF"
PURPLE, GREEN = "#9B30FF", "#00A651"            # F1 timing colours: fastest / personal best
TYRES = [  # (letter, colour) in the order the tech-stack rows use them
    ("S", "#DB0B44"), ("M", "#FFD200"), ("H", "#FFFFFF"), ("I", "#43B047"), ("W", "#0067AD"), ("S", "#DB0B44"), ("M", "#FFD200"),
]
TEAM_COLOURS = {  # constructorId from the F1 API -> team colour (colour only, no logos)
    "mercedes": "#27F4D2", "ferrari": "#E8002D", "red_bull": "#3671C6", "mclaren": "#FF8000",
    "aston_martin": "#229971", "alpine": "#FF87BC", "williams": "#64C4FF", "rb": "#6692FF",
    "sauber": "#52E252", "audi": "#BB0A30", "haas": "#B6BABD", "cadillac": "#AAAAAD",
}
POSTER_SERIF = "Georgia,'Times New Roman',serif"
BLACK_SANS = "'Helvetica Neue','Arial Black',Arial,sans-serif"
F1_API = "https://api.jolpi.ca/ergast/f1/current/driverStandings.json"
MARGIN = 60                                       # left and right margin inside the poster
INNER = W - 2 * MARGIN                            # usable width


# --------------------------------------------------------------------------
# Extra data
# --------------------------------------------------------------------------
def fetch_f1_standings() -> dict | None:
    """Current Formula 1 drivers' championship from the free Jolpica F1 API.

    No GitHub token is sent here: it is only for the GitHub API. If the API is
    down, the section is simply left out so the rest of the profile still builds.
    """
    try:
        req = urllib.request.Request(F1_API, headers={"User-Agent": f"{LOGIN}-profile-panels"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            table = json.load(resp)["MRData"]["StandingsTable"]["StandingsLists"][0]
        drivers = []
        for row in table["DriverStandings"][:10]:
            team = (row.get("Constructors") or [{}])[-1]
            drivers.append({
                "position": int(row["position"]), "code": row["Driver"].get("code") or row["Driver"]["familyName"][:3].upper(),
                "name": f'{row["Driver"]["givenName"]} {row["Driver"]["familyName"]}', "team": team.get("name", ""),
                "team_id": team.get("constructorId", ""), "points": float(row["points"]), "wins": int(row["wins"]),
            })
        return {"season": table["season"], "round": table["round"], "drivers": drivers}
    except (urllib.error.URLError, KeyError, IndexError, ValueError) as exc:
        print("F1 standings unavailable, section skipped:", exc, file=sys.stderr)
        return None


def weekly_contributions(days: dict[dt.date, int], today: dt.date, weeks: int = 26) -> list[dict]:
    """Contributions and active days for each of the last `weeks` weeks (oldest first)."""
    start = today - dt.timedelta(days=7 * weeks - 1)
    out = []
    for w in range(weeks):
        first = start + dt.timedelta(days=7 * w)
        span = [first + dt.timedelta(days=d) for d in range(7)]
        out.append({"start": first, "total": sum(days.get(d, 0) for d in span),
                    "active": sum(1 for d in span if days.get(d, 0) > 0)})
    return out


# --------------------------------------------------------------------------
# Drawing helpers
# --------------------------------------------------------------------------
def esc(value) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;")


def short(n: float) -> str:
    """1234 -> '1.2k'"""
    return f"{n / 1000:.1f}k" if n >= 1000 else f"{n:g}"


def text(x, y, content, size=16, fill=INK, weight=400, anchor="start", family=SANS, extra="") -> str:
    return (f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="{family}" font-weight="{weight}" '
            f'font-size="{size}" fill="{fill}" {extra}>{esc(content)}</text>')


def fmt_date(day: dt.date | None, today: dt.date) -> str:
    if day is None:
        return "-"
    label = f"{day:%b} {day.day}"
    return label if day.year == today.year else f"{label}, {day.year}"


def fmt_range(streak: dict, today: dt.date) -> str:
    return "-" if not streak["length"] else f'{fmt_date(streak["start"], today)} - {fmt_date(streak["end"], today)}'


def ink_safe(colour: str) -> str:
    """Brand colours that are near-white would vanish on the paper, so draw them in ink instead."""
    c = colour.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    return INK if (0.299 * r + 0.587 * g + 0.114 * b) > 200 else colour


def section_header(title: str, note: str) -> str:
    """Editorial header: thick black rule, bold title on the left, small grey note on the right."""
    return (f'<rect x="{MARGIN}" y="0" width="{INNER}" height="4" fill="{INK}"/>'
            f'<rect x="{MARGIN}" y="0" width="90" height="4" fill="{RED}"/>'
            + text(MARGIN, 44, title.upper(), 30, INK, 900, family=BLACK_SANS, extra='letter-spacing="1"')
            + text(W - MARGIN, 40, note.upper(), 12, MUTED, 700, "end", MONO, 'letter-spacing="2"'))


HEAD = 76   # height of a section header


def tyre(cx: float, cy: float, letter: str, colour: str, r: int = 15) -> str:
    """Tyre icon as used on F1 strategy graphics: black tyre with a coloured compound band."""
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{INK}"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r - 4}" fill="none" stroke="{colour}" stroke-width="3.5"/>'
            + text(cx, cy + 4.5, letter, 12, WHITE, 900, "middle"))



def pill_width(item: dict, padding: int) -> int:
    return padding + item.get("text_width", round(len(item["label"]) * 9.2))


# --------------------------------------------------------------------------
# Sections. Each returns (svg, height), drawn from y = 0.
# --------------------------------------------------------------------------
def poster_top(profile: dict, streaks: dict, stats: dict) -> tuple[str, int]:
    """The poster: swatches, number, names, picture, quote, emblem rule and stats bar."""
    banner = Path(__file__).resolve().parent.parent / profile["banner"]
    encoded = base64.b64encode(banner.read_bytes()).decode()
    swatches = "".join(f'<rect x="{MARGIN + i * 26}" y="56" width="22" height="22" fill="{c}" stroke="{RULE}"/>'
                       for i, c in enumerate([WHITE, INK, NAVY, RED, YELLOW]))
    parts = [
        swatches,
        text(W - MARGIN, 78, f'/{profile["race_number"]}', 34, INK, 400, "end", POSTER_SERIF),
        text(MARGIN, 150, profile["first_name"], 46, INK, 400, family=POSTER_SERIF),
        text(MARGIN - 6, 300, profile["last_name"].upper(), 178, INK, 900, family=BLACK_SANS, extra='letter-spacing="-5"'),
        text(MARGIN, 340, "  ·  ".join(r.upper() for r in profile["roles"]), 14, MUTED, 700, family=MONO, extra='letter-spacing="2"'),
    ]
    # picture block (dark, like the photo on the poster)
    by, bh_box = 368, 420
    iw = INNER - 80
    ih = round(iw * profile["banner_height"] / profile["banner_width"])
    parts += [
        f'<rect x="{MARGIN}" y="{by}" width="{INNER}" height="{bh_box}" fill="{NAVY}"/>',
        f'<text x="{W - MARGIN - 20}" y="{by + bh_box - 24}" text-anchor="end" font-family="{BLACK_SANS}" font-weight="900" '
        f'font-size="300" fill="none" stroke="{WHITE}" stroke-opacity="0.10" stroke-width="2">{profile["race_number"]}</text>',
        f'<image x="{MARGIN + 40}" y="{by + (bh_box - ih) / 2:.0f}" width="{iw}" height="{ih}" href="data:image/png;base64,{encoded}"/>',
        text(MARGIN + 26, by + 46, profile["signature"], 30, WHITE, 400, family="'Snell Roundhand','Brush Script MT',cursive",
             extra='font-style="italic" opacity="0.9" transform="rotate(-6 100 400)"'),
    ]
    # quote and emblem rule
    qy = by + bh_box + 58
    for i, line in enumerate(profile["quote_lines"]):
        parts.append(text(600, qy + i * 28, line, 19, INK, 400, "middle", POSTER_SERIF, 'font-style="italic"'))
    ry = qy + 28 * (len(profile["quote_lines"]) - 1) + 44
    parts += [
        f'<rect x="{MARGIN + 60}" y="{ry}" width="{INNER / 2 - 100}" height="1.2" fill="{INK}"/>',
        f'<rect x="{W / 2 + 40}" y="{ry}" width="{INNER / 2 - 100}" height="1.2" fill="{INK}"/>',
        f'<circle cx="600" cy="{ry}" r="17" fill="none" stroke="{INK}" stroke-width="1.5"/>',
        text(600, ry + 5, profile["monogram"], 13, INK, 700, "middle", POSTER_SERIF),
    ]
    # stats bar
    sy = ry + 40
    grade, _ = rank(stats)
    cells = [(f'{streaks["total"]:,}', "total", "contributions"), (str(streaks["longest"]["length"]), "day longest", "streak"),
             (short(stats["commits"]), "total", "commits"), (str(stats["prs"]), "pull", "requests"),
             (str(stats["stars"]), "stars", "earned"), (grade, "power", "level")]
    parts.append(f'<rect x="{MARGIN}" y="{sy}" width="{INNER}" height="64" fill="{PAPER2}"/>')
    cell = INNER / len(cells)
    for i, (value, l1, l2) in enumerate(cells):
        cx = MARGIN + i * cell + 26
        parts.append(text(cx, sy + 43, value, 30, INK, 900, family=BLACK_SANS))
        lx = cx + len(value) * 19 + 8
        parts.append(text(lx, sy + 30, l1, 11, MUTED, 600))
        parts.append(text(lx, sy + 44, l2, 11, MUTED, 600))
    return "\n    ".join(parts), sy + 64 + 64


def bio_section(profile: dict, capabilities: list[dict]) -> tuple[str, int]:
    """Driver bio (intro text) on the left, core capabilities as a setup sheet on the right."""
    parts = [section_header("Driver Bio", "Core capabilities")]
    for i, line in enumerate(profile["bio_lines"]):
        parts.append(text(MARGIN, HEAD + 40 + i * 28, line, 17, INK, 400, family=POSTER_SERIF))
    x = 700
    for i, item in enumerate(capabilities):
        y = HEAD + 30 + i * 34
        parts.append(f'<rect x="{x}" y="{y - 13}" width="4" height="16" fill="{RED if i % 2 == 0 else NAVY}"/>')
        parts.append(text(x + 16, y, item["label"], 16, INK, 700))
        parts.append(f'<rect x="{x + 16}" y="{y + 10}" width="{INNER + MARGIN - x - 16}" height="1" fill="{RULE}"/>')
    height = max(HEAD + 40 + 28 * len(profile["bio_lines"]), HEAD + 30 + 34 * len(capabilities)) + 30
    return "\n    ".join(parts), height


def sector_section(streaks: dict, today: dt.date) -> tuple[str, int]:
    """Three cells coloured like F1 sector times: yellow, green (personal best), purple (fastest)."""
    parts = [section_header("Sector Times", "Contribution streaks")]
    cells = [("S1", "Total contributions", f'{streaks["total"]:,}', f'{fmt_date(streaks["first"], today)} - Present', YELLOW),
             ("S2", "Current streak", f'{streaks["current"]["length"]} days', fmt_range(streaks["current"], today), GREEN),
             ("S3", "Longest streak", f'{streaks["longest"]["length"]} days', fmt_range(streaks["longest"], today), PURPLE)]
    gap = 16
    cw = (INNER - 2 * gap) / 3
    y = HEAD + 14
    for i, (sector, label, value, sub, colour) in enumerate(cells):
        x = MARGIN + i * (cw + gap)
        parts += [
            f'<rect x="{x:.1f}" y="{y}" width="{cw:.1f}" height="130" fill="{WHITE}" stroke="{RULE}"/>',
            f'<rect x="{x:.1f}" y="{y}" width="{cw:.1f}" height="8" fill="{colour}"/>',
            text(x + 20, y + 38, sector, 14, MUTED, 800, family=MONO),
            text(x + 20, y + 84, value, 38, INK, 900, family=BLACK_SANS),
            text(x + 20, y + 112, f"{label.upper()}  ·  {sub}", 12, MUTED, 700, family=MONO),
        ]
    return "\n    ".join(parts), y + 130 + 40


def speed_trace(weeks: list[dict]) -> tuple[str, int]:
    """Telemetry-style line chart: contributions per week (speed) and active days per week (throttle)."""
    parts = [section_header("Speed Trace", f"Last {len(weeks)} weeks · contributions per week")]
    x0, x1 = MARGIN + 46, W - MARGIN
    top, chart_h = HEAD + 24, 210
    peak = max(1, max(w["total"] for w in weeks))
    scale_max = max(4, -(-peak // 4) * 4)                     # round up to a multiple of 4
    step = (x1 - x0) / (len(weeks) - 1)
    px = lambda i: x0 + i * step
    py = lambda v: top + chart_h - chart_h * v / scale_max
    for k in range(5):                                         # grid lines and y labels
        v = scale_max * k / 4
        parts.append(f'<rect x="{x0}" y="{py(v):.1f}" width="{x1 - x0}" height="1" fill="{RULE}"/>')
        parts.append(text(x0 - 10, py(v) + 4, f"{v:g}", 11, MUTED, 600, "end", MONO))
    points = " ".join(f"{px(i):.1f},{py(w['total']):.1f}" for i, w in enumerate(weeks))
    parts.append(f'<polygon points="{x0},{py(0):.1f} {points} {x1},{py(0):.1f}" fill="{NAVY}" fill-opacity="0.10"/>')
    parts.append(f'<polyline points="{points}" fill="none" stroke="{NAVY}" stroke-width="3" stroke-linejoin="round"/>')
    avg = sum(w["total"] for w in weeks) / len(weeks)
    parts.append(f'<rect x="{x0}" y="{py(avg):.1f}" width="{x1 - x0}" height="1.5" fill="{RED}" opacity="0.8"/>')
    parts.append(text(x1, py(avg) - 6, f"AVG {avg:.1f}/WK", 11, RED, 800, "end", MONO))
    best = max(range(len(weeks)), key=lambda i: weeks[i]["total"])
    parts.append(f'<circle cx="{px(best):.1f}" cy="{py(weeks[best]["total"]):.1f}" r="7" fill="{PURPLE}" stroke="{WHITE}" stroke-width="2"/>')
    parts.append(text(px(best), py(weeks[best]["total"]) - 14, f'FASTEST WEEK · {weeks[best]["total"]}', 11, PURPLE, 800,
                      "middle" if 0 < best < len(weeks) - 3 else "end", MONO))
    # throttle trace: active days per week as bars (0-7)
    ty, th = top + chart_h + 46, 46
    parts.append(text(x0, ty - 8, "THROTTLE  ·  ACTIVE DAYS PER WEEK", 11, MUTED, 800, family=MONO))
    for i, w in enumerate(weeks):
        h = th * w["active"] / 7
        colour = GREEN if w["active"] >= 5 else (YELLOW if w["active"] >= 2 else RULE)
        parts.append(f'<rect x="{px(i) - step * 0.35:.1f}" y="{ty + th - h:.1f}" width="{step * 0.7:.1f}" height="{max(h, 2):.1f}" fill="{colour}"/>')
    # month labels
    last_month, last_x = None, -100
    for i, w in enumerate(weeks):
        if w["start"].month != last_month:
            last_month = w["start"].month
            if px(i) - last_x > 50:                            # skip a label that would overlap the previous one
                parts.append(text(px(i), ty + th + 22, f'{w["start"]:%b}'.upper(), 11, MUTED, 700, "middle", MONO))
                last_x = px(i)
    return "\n    ".join(parts), ty + th + 22 + 46


def tower_section(stats: dict) -> tuple[str, int]:
    """Timing tower of languages on the left, car telemetry (stats and grade) on the right."""
    parts = [section_header("Timing Tower", "Languages by share of code")]
    y0, row = HEAD + 10, 34
    langs = stats["languages"]
    for i, lang in enumerate(langs):
        y = y0 + i * row
        interval = "LEADER" if i == 0 else f'+{langs[i - 1]["percent"] - lang["percent"]:.1f}%'
        parts += [
            f'<rect x="{MARGIN}" y="{y}" width="560" height="{row - 4}" fill="{WHITE if i % 2 == 0 else PAPER2}"/>',
            f'<rect x="{MARGIN}" y="{y}" width="36" height="{row - 4}" fill="{INK}"/>',
            text(MARGIN + 18, y + 21, i + 1, 15, WHITE, 900, "middle"),
            f'<rect x="{MARGIN + 44}" y="{y + 5}" width="5" height="{row - 14}" fill="{lang["color"]}"/>',
            text(MARGIN + 60, y + 21, lang["name"].upper(), 15, INK, 800),
            text(MARGIN + 430, y + 21, f'{lang["percent"]:.2f}%', 14, INK, 700, "end", MONO),
            text(MARGIN + 548, y + 21, interval, 13, PURPLE if i == 0 else MUTED, 700, "end", MONO),
        ]
    # car telemetry card
    cx, cw = MARGIN + 600, INNER - 600
    ch = row * len(langs) - 4
    grade, percentile = rank(stats)
    parts.append(f'<rect x="{cx}" y="{y0}" width="{cw}" height="{ch}" fill="{NAVY}"/>')
    parts.append(text(cx + 24, y0 + 36, "CAR TELEMETRY", 13, YELLOW, 800, family=MONO, extra='letter-spacing="3"'))
    rows = [("Stars earned", stats["stars"]), ("Commits", stats["commits"]), ("Pull requests", stats["prs"]),
            ("Issues", stats["issues"]), ("Contributed to (last year)", stats["contributed_to"])]
    for i, (label, value) in enumerate(rows):
        ry = y0 + 74 + i * 34
        parts.append(text(cx + 24, ry, label, 15, CAN, 600))
        parts.append(text(cx + 290, ry, short(value), 16, WHITE, 900, "end", MONO))
        parts.append(f'<rect x="{cx + 24}" y="{ry + 10}" width="266" height="1" fill="{WHITE}" opacity="0.15"/>')
    rcx, rcy, r = cx + cw - 90, y0 + ch / 2 + 10, 50
    circ = 2 * 3.14159265 * r
    parts += [
        text(rcx, y0 + 36, "POWER LEVEL", 11, CAN, 800, "middle", MONO),
        f'<circle cx="{rcx}" cy="{rcy}" r="{r}" fill="none" stroke="{WHITE}" stroke-opacity="0.15" stroke-width="8"/>',
        f'<circle cx="{rcx}" cy="{rcy}" r="{r}" fill="none" stroke="{RED}" stroke-width="8" stroke-linecap="round" '
        f'stroke-dasharray="{circ * (100 - percentile) / 100:.1f} {circ:.1f}" transform="rotate(-90 {rcx} {rcy})"/>',
        text(rcx, rcy + 12, grade, 34, WHITE, 900, "middle", BLACK_SANS),
    ]
    return "\n    ".join(parts), y0 + ch + 40


def strategy_section(categories: list[dict]) -> tuple[str, int]:
    """Tech stack drawn like a tyre-strategy chart: one row per category, one stint per technology."""
    parts = [section_header("Tyre Strategy", "Tech stack · one stint per technology")]
    y = HEAD + 6
    x_start = MARGIN + 250
    width = W - MARGIN - x_start
    for n, cat in enumerate(categories):
        letter, colour = TYRES[n % len(TYRES)]
        parts.append(tyre(MARGIN + 15, y + 20, letter, colour))
        parts.append(text(MARGIN + 42, y + 25, cat["category"].upper(), 13, INK, 800))
        natural = [pill_width(i, 13 + 16 + 8 + 10) for i in cat["items"]]
        factor = width / sum(natural)
        x = x_start
        stripe = INK if colour == "#FFFFFF" else colour
        for item, nw in zip(cat["items"], natural):
            w = nw * factor
            icon = (f'<path d="{item["icon"]}" fill="{ink_safe(item.get("colour", INK))}" transform="translate({x + 10:.1f},{y + 13}) scale({16 / 24})"/>'
                    if item.get("icon") else f'<rect x="{x + 13:.1f}" y="{y + 16}" width="10" height="10" fill="{item.get("colour", INK)}" transform="rotate(45 {x + 18:.1f} {y + 21})"/>')
            parts += [
                f'<rect x="{x:.1f}" y="{y + 4}" width="{w - 3:.1f}" height="34" fill="{WHITE}" stroke="{RULE}"/>',
                f'<rect x="{x:.1f}" y="{y + 4}" width="{w - 3:.1f}" height="5" fill="{stripe}"/>',
                icon,
                f'<text x="{x + 32:.1f}" y="{y + 30}" font-family="{SANS}" font-weight="700" font-size="13" fill="{INK}" '
                f'textLength="{min(w - 42, item.get("text_width", 60) * 0.85):.1f}" lengthAdjust="spacingAndGlyphs">{esc(item["label"])}</text>',
            ]
            x += w
        y += 50
    legend = "   ".join(f"{l} = {name}" for l, name in (("S", "SOFT"), ("M", "MEDIUM"), ("H", "HARD"), ("I", "INTER"), ("W", "WET")))
    parts.append(text(W - MARGIN, y + 16, legend, 11, MUTED, 700, "end", MONO))
    return "\n    ".join(parts), y + 16 + 40


def standings_section(standings: dict) -> tuple[str, int]:
    """Live Formula 1 drivers' championship, drawn as a broadcast timing tower."""
    parts = [section_header(f'{standings["season"]} Drivers\' Championship',
                            f'Live · after round {standings["round"]} · refreshed every 12 hours')]
    y0, row = HEAD + 10, 36
    leader = standings["drivers"][0]["points"] if standings["drivers"] else 0
    for i, d in enumerate(standings["drivers"]):
        y = y0 + i * row
        colour = TEAM_COLOURS.get(d["team_id"], MUTED)
        gap = "LEADER" if i == 0 else f'-{leader - d["points"]:g}'
        parts += [
            f'<rect x="{MARGIN}" y="{y}" width="{INNER}" height="{row - 4}" fill="{WHITE if i % 2 == 0 else PAPER2}"/>',
            f'<rect x="{MARGIN}" y="{y}" width="40" height="{row - 4}" fill="{INK}"/>',
            text(MARGIN + 20, y + 22, d["position"], 15, WHITE, 900, "middle"),
            f'<rect x="{MARGIN + 48}" y="{y + 5}" width="5" height="{row - 14}" fill="{colour}"/>',
            text(MARGIN + 66, y + 22, d["code"], 16, INK, 900, family=BLACK_SANS),
            text(MARGIN + 140, y + 22, d["name"], 15, INK, 600),
            text(MARGIN + 470, y + 22, d["team"].upper(), 12, MUTED, 700, family=MONO),
            text(MARGIN + 840, y + 22, f'{d["wins"]} WINS' if d["wins"] else "", 12, MUTED, 700, "end", MONO),
            text(MARGIN + 960, y + 22, f'{d["points"]:g} PTS', 15, INK, 900, "end", MONO),
            text(W - MARGIN - 12, y + 22, gap, 13, PURPLE if i == 0 else MUTED, 700, "end", MONO),
        ]
    parts.append(text(MARGIN, y0 + row * len(standings["drivers"]) + 18,
                      "Data: Jolpica F1 API (community-run). Team colours only; no team or series logos.", 11, MUTED, 600, family=MONO))
    return "\n    ".join(parts), y0 + row * len(standings["drivers"]) + 18 + 40


def radio_section(messages: list[str]) -> tuple[str, int]:
    """Team radio caption, like the ones on F1 broadcasts. One message every few seconds."""
    parts = [section_header("Team Radio", "Race engineer")]
    hold, x, y, w, h = 4, MARGIN, HEAD + 10, INNER, 92
    cycle = hold * len(messages)
    share = 1 / len(messages)
    parts += [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{NAVY}"/>',
        f'<rect x="{x}" y="{y}" width="8" height="{h}" fill="{RED}"/>',
        text(x + 30, y + 30, "RACE ENGINEER", 12, YELLOW, 800, family=MONO, extra='letter-spacing="3"'),
        f'<circle cx="{x + w - 70}" cy="{y + 26}" r="6" fill="{RED}"><animate attributeName="opacity" values="1;0.2;1" dur="1.2s" repeatCount="indefinite"/></circle>',
        text(x + w - 26, y + 31, "LIVE", 12, WHITE, 900, "end", MONO),
    ]
    for i, message in enumerate(messages):
        parts.append(
            f'<g opacity="0">{text(x + 30, y + 68, "“" + message + "”", 24, WHITE, 400, family=POSTER_SERIF, extra="font-style=\"italic\"")}'
            f'<animate attributeName="opacity" values="0;1;1;0;0" keyTimes="0;{share * 0.08:.3f};{share * 0.9:.3f};{share:.3f};1" '
            f'dur="{cycle}s" begin="{i * hold}s;{i * hold}s+{cycle}s" repeatCount="indefinite"/></g>')
    return "\n    ".join(parts), y + h + 40


def track_section(snake_svg: str) -> tuple[str, int]:
    """The contribution snake, drawn as the race track, with a chequered start line."""
    parts = [section_header("Race Track", "Contribution activity")]
    root = re.search(r"<svg\b[^>]*>", snake_svg)
    view = re.search(r'viewBox="([^"]+)"', root.group(0)) if root else None
    if not root or not view:
        raise RuntimeError("Snake file is not in the expected SVG format")
    _, _, vw, vh = (float(v) for v in view.group(1).split())
    inner = snake_svg[root.end(): snake_svg.rindex("</svg>")]
    width = INNER - 40
    h = round(width * vh / vw)
    top = HEAD + 6
    flag = "".join(f'<rect x="{MARGIN + (r % 2) * 8}" y="{top + 16 + r * 8}" width="8" height="8" fill="{INK}"/>'
                   for r in range(int(h / 8) - 4))
    parts += [flag, f'<svg x="{MARGIN + 40}" y="{top}" width="{width}" height="{h}" viewBox="{view.group(1)}">{inner}</svg>']
    return "\n    ".join(parts), top + h + 20


# --------------------------------------------------------------------------
# Racing cars (top-down drawing) that race down the poster
# --------------------------------------------------------------------------
def car_shape(scale: float, body: str) -> str:
    """Top-down F1 car pointing right (+x), centred on its middle, about 120 x 48 units before scaling."""
    t = lambda x, y, w, h: f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="{INK}"/>'
    return f'''<g transform="scale({scale})"><g transform="translate(-60,0)">
      <rect x="0" y="-22" width="12" height="44" rx="2" fill="{RED}"/><rect x="2" y="-22" width="3" height="44" fill="{YELLOW}"/>
      {t(14, -26, 24, 13)}{t(14, 13, 24, 13)}
      <path d="M10,-9 L30,-16 L62,-17 L74,-9 L74,9 L62,17 L30,16 L10,9 Z" fill="{body}"/>
      <path d="M34,-16 L60,-16 L60,-12 L34,-11 Z M34,16 L60,16 L60,12 L34,11 Z" fill="{RED}"/>
      <path d="M60,-7 L104,-4 L114,0 L104,4 L60,7 Z" fill="{body}"/><path d="M106,-3 L114,0 L106,3 Z" fill="{YELLOW}"/>
      <ellipse cx="58" cy="0" rx="10" ry="6" fill="#05081C"/><circle cx="56" cy="0" r="4.2" fill="{YELLOW}"/>
      {t(76, -27, 20, 12)}{t(76, 15, 20, 12)}
      <path d="M108,-24 L118,-22 L118,22 L108,24 Z" fill="{RED}"/><rect x="112" y="-22" width="3" height="44" fill="{YELLOW}"/>
    </g></g>'''


def race_cars(height: int) -> str:
    """Two small cars racing down the poster on a zigzag line, swapping the lead (see keyPoints)."""
    import math
    top, bottom, amplitude, wavelength = 40, height - 40, (W - 140) / 2, 520

    def line(shift: float) -> str:
        pts = [f"{600 + amplitude * math.sin(2 * math.pi * (y - top) / wavelength):.1f},{y + shift}"
               for y in range(top, bottom + 1, 8)]
        return "M" + " L".join(pts)

    run = round(((bottom - top) / wavelength) * 4 * amplitude / 700)
    out = []
    for path_id, shift, body, pace in (("lineA", 0, NAVY, "0;0.30;0.48;0.78;1"), ("lineB", 26, BLUE, "0;0.24;0.55;0.72;1")):
        out.append(f'''<path id="{path_id}" d="{line(shift)}" fill="none" stroke="none"/>
    <g><rect x="-48" y="-1.5" width="36" height="3" rx="1.5" fill="url(#trail)"/>{car_shape(0.24, body)}
      <animateMotion dur="{run}s" repeatCount="indefinite" rotate="auto" calcMode="linear" keyPoints="{pace}" keyTimes="0;0.25;0.5;0.75;1"><mpath href="#{path_id}"/></animateMotion></g>''')
    return "\n    ".join(out)


# --------------------------------------------------------------------------
# Whole poster
# --------------------------------------------------------------------------
def build_profile(content: dict, days: dict, streaks: dict, stats: dict, standings: dict | None,
                  snake_svg: str, today: dt.date) -> str:
    profile = content["profile"]
    sections = [
        poster_top(profile, streaks, stats),
        bio_section(profile, content["capabilities"]),
        sector_section(streaks, today),
        speed_trace(weekly_contributions(days, today)),
        tower_section(stats),
        strategy_section(content["tech_stack"]),
    ]
    if standings and standings["drivers"]:
        sections.append(standings_section(standings))
    sections += [radio_section(content["radio_messages"]), track_section(snake_svg)]

    blocks, y = [], 0
    for body, height in sections:
        blocks.append(f'<g transform="translate(0,{y})">\n    {body}\n    </g>')
        y += height
    foot = y + 10
    blocks.append(f'<rect x="{MARGIN}" y="{foot}" width="{INNER}" height="1.2" fill="{INK}"/>')
    blocks.append(text(MARGIN, foot + 28, f"{profile['first_name']} {profile['last_name']}  ·  #{profile['race_number']}", 12, INK, 800, family=MONO))
    blocks.append(text(W - MARGIN, foot + 28, "DATA: GITHUB API · JOLPICA F1 API · REFRESHED EVERY 12 HOURS", 11, MUTED, 700, "end", MONO))
    paper_h = foot + 60
    height = paper_h + 36                          # black poster frame around the paper

    grade, _ = rank(stats)
    label = (f'{profile["first_name"]} {profile["last_name"]}, number {profile["race_number"]}. {" | ".join(profile["roles"])}. '
             f'{" ".join(profile["bio_lines"])} Core capabilities: ' + ", ".join(i["label"] for i in content["capabilities"]) + ". "
             f'{streaks["total"]} total contributions, longest streak {streaks["longest"]["length"]} days, power level {grade}. '
             "Tech stack: " + " ".join(f'{c["category"]}: {", ".join(i["label"] for i in c["items"])}.' for c in content["tech_stack"]))
    joined = "\n    ".join(blocks)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height}" width="{W}" height="{height}" role="img" aria-label="{esc(label)}">
  <title>{esc(label)}</title>
  <style>@media (prefers-reduced-motion: reduce) {{ .fx {{ display: none; }} }}</style>
  <defs>
    <linearGradient id="trail" x1="0" x2="1"><stop offset="0" stop-color="{RED}" stop-opacity="0"/><stop offset="1" stop-color="{RED}" stop-opacity="0.8"/></linearGradient>
    <clipPath id="paper"><rect x="18" y="18" width="{W - 36}" height="{paper_h}"/></clipPath>
  </defs>
  <rect width="{W}" height="{height}" rx="6" fill="#1A1A1A"/>
  <rect x="18" y="18" width="{W - 36}" height="{paper_h}" fill="{PAPER}"/>
  <g clip-path="url(#paper)">
    <g transform="translate(0,18)">
    {joined}
    </g>
    <g class="fx">
    {race_cars(height)}
    </g>
  </g>
</svg>
'''


def main() -> None:
    if not TOKEN:
        sys.exit("GITHUB_TOKEN is not set")
    if not SNAKE_FILE.exists():
        sys.exit(f"{SNAKE_FILE} not found; the snake must be generated before this script runs")
    content = json.loads(CONTENT_FILE.read_text(encoding="utf-8"))
    today = dt.datetime.now(dt.timezone.utc).date()
    days = fetch_contribution_days()
    streaks = compute_streaks(days, today)
    stats = fetch_stats()
    standings = fetch_f1_standings()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    svg = build_profile(content, days, streaks, stats, standings, SNAKE_FILE.read_text(encoding="utf-8"), today)
    (OUT_DIR / "profile.svg").write_text(svg, encoding="utf-8")
    print(f'Wrote {OUT_DIR}/profile.svg (total {streaks["total"]}, grade {rank(stats)[0]}, '
          f'F1 standings {"included" if standings else "skipped"})')


if __name__ == "__main__":
    main()
