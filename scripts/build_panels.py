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

    Poster -> Driver Status -> Trophy Cabinet -> Sector Times -> Speed Trace
    -> Timing Tower -> Tyre Strategy -> Team Radio -> Race Track

Inputs
    GITHUB_TOKEN                  token for the GitHub API (provided by GitHub Actions)
    GH_USER                       GitHub login to read statistics for
    OUT_DIR                       folder holding github-snake-dark.svg; output goes here
    scripts/profile_content.json  name, quote, driver status, trophies, tech stack and radio messages
    assets/car-blueprint.jpg      picture shown in the card under the name

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
# Blueprint palette: blue paper, white "ink" lines and text, like a cyanotype drawing
PAPER, PAPER2, INK, MUTED, RULE = "#1D4A93", "#173E7E", "#EEF3FF", "#AFC3E6", "#5A82C4"
DARK = "#0A1430"                                  # for things that stay dark: tyres, position boxes, text outlines
CARD_BG = "#22549E"                               # slightly lighter blue cards that sit on the paper
NAVY, BLUE, CAN = "#233268", "#1D19AF", "#F4ECEF"
RED, YELLOW = "#B8343F", "#D9B13B"                # team red and yellow, aged slightly to suit the paper
WHITE = "#FFFFFF"
PANEL = "#0C1E4A"                                 # deep ink blue for the dark panels
PANEL_AGEING = 0.4                                # how strongly the paper stains show through the dark panels
PURPLE, GREEN = "#C77DFF", "#3DDC84"            # F1 timing colours: fastest / personal best
TYRES = [  # (letter, colour) in the order the tech-stack rows use them
    ("S", "#B8343F"), ("M", "#D9B13B"), ("H", "#FFFFFF"), ("I", "#43B047"), ("W", "#0067AD"), ("S", "#B8343F"), ("M", "#D9B13B"),
]
POSTER_SERIF = "Georgia,'Times New Roman',serif"
BLACK_SANS = "'Helvetica Neue','Arial Black',Arial,sans-serif"
MARGIN = 60                                       # left and right margin inside the poster
INNER = W - 2 * MARGIN                            # usable width


# --------------------------------------------------------------------------
# Extra data
# --------------------------------------------------------------------------
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
    """Brand colours that are near-black would vanish on the blue paper, so draw them in light ink instead."""
    c = colour.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    return INK if (0.299 * r + 0.587 * g + 0.114 * b) < 70 else colour


def panel(x: float, y: float, w: float, h: float, rx: float = 0) -> str:
    """A dark panel, optionally aged with the same stain texture as the paper so it blends in."""
    out = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{PANEL}"/>'
    if PANEL_AGEING:
        out += (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" filter="url(#stains)" opacity="{PANEL_AGEING}"/>'
                f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" filter="url(#grain)" opacity="{PANEL_AGEING}"/>')
    return out


def section_header(title: str) -> str:
    """Editorial header: thick black rule with a red start, and a bold title."""
    return (f'<rect x="{MARGIN}" y="0" width="{INNER}" height="4" fill="{INK}"/>'
            f'<rect x="{MARGIN}" y="0" width="90" height="4" fill="{RED}"/>'
            + text(MARGIN, 44, title.upper(), 30, INK, 900, family=BLACK_SANS, extra='letter-spacing="1"'))


HEAD = 76   # height of a section header


def tyre(cx: float, cy: float, letter: str, colour: str, r: int = 15) -> str:
    """Tyre icon as used on F1 strategy graphics: black tyre with a coloured compound band."""
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{DARK}"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r - 4}" fill="none" stroke="{colour}" stroke-width="3.5"/>'
            + text(cx, cy + 4.5, letter, 12, WHITE, 900, "middle"))



def pill_width(item: dict, padding: int) -> int:
    return padding + item.get("text_width", round(len(item["label"]) * 9.2))


# --------------------------------------------------------------------------
# Sections. Each returns (svg, height), drawn from y = 0.
# --------------------------------------------------------------------------
def name_card(profile: dict, x: float, y: float, w: float, h: float) -> str:
    """Picture card: the car sketch fills the card, and the role sits on the empty paper above the car.

    An SVG shown as an image cannot load a separate picture file, so the
    picture is read from the repository and embedded as text (a base64 "data URI").
    """
    picture = Path(__file__).resolve().parent.parent / profile["card_image"]
    encoded = base64.b64encode(picture.read_bytes()).decode()
    outline = f'stroke="{DARK}" stroke-width="3" paint-order="stroke" stroke-linejoin="round"'
    return f'''<g>
      <mask id="cardfade"><rect x="{x + 26}" y="{y + 26}" width="{w - 52}" height="{h - 52}" fill="white" filter="url(#soft)"/></mask>
      <image x="{x}" y="{y}" width="{w}" height="{h}" preserveAspectRatio="xMidYMid slice" mask="url(#cardfade)" href="data:image/jpeg;base64,{encoded}"/>
      {text(x + 40, y + 84, profile["card_role"].upper(), 62, YELLOW, 900, family=BLACK_SANS, extra=f'font-style="italic" letter-spacing="1" {outline}')}
      {text(x + 44, y + 118, profile["card_sub"].upper(), 14, INK, 800, family=MONO, extra='letter-spacing="4"')}
      <rect x="{x + 44}" y="{y + 130}" width="70" height="4" fill="{RED}"/><rect x="{x + 118}" y="{y + 130}" width="24" height="4" fill="{YELLOW}"/>
    </g>'''


def poster_top(profile: dict, streaks: dict, stats: dict) -> tuple[str, int]:
    """The poster: number, names, picture card, quote, emblem rule and stats bar."""
    parts = [
        text(W - MARGIN, 78, f'/{profile["race_number"]}', 34, INK, 400, "end", POSTER_SERIF),
        text(MARGIN, 150, profile["first_name"], 46, INK, 400, family=POSTER_SERIF),
        text(MARGIN - 6, 300, profile["last_name"].upper(), 178, INK, 900, family=BLACK_SANS, extra='letter-spacing="-5"'),
    ]
    # picture card (the car sketch, with the role on top)
    by, bh_box = 344, 480
    parts.append(name_card(profile, MARGIN, by, INNER, bh_box))
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


def sector_section(streaks: dict, today: dt.date) -> tuple[str, int]:
    """Three cells coloured like F1 sector times: yellow, green (personal best), purple (fastest)."""
    parts = [section_header("Sector Times")]
    cells = [("S1", "Total contributions", f'{streaks["total"]:,}', f'{fmt_date(streaks["first"], today)} - Present', YELLOW),
             ("S2", "Current streak", f'{streaks["current"]["length"]} days', fmt_range(streaks["current"], today), GREEN),
             ("S3", "Longest streak", f'{streaks["longest"]["length"]} days', fmt_range(streaks["longest"], today), PURPLE)]
    gap = 16
    cw = (INNER - 2 * gap) / 3
    y = HEAD + 14
    for i, (sector, label, value, sub, colour) in enumerate(cells):
        x = MARGIN + i * (cw + gap)
        parts += [
            f'<rect x="{x:.1f}" y="{y}" width="{cw:.1f}" height="130" fill="{CARD_BG}" stroke="{RULE}"/>',
            f'<rect x="{x:.1f}" y="{y}" width="{cw:.1f}" height="8" fill="{colour}"/>',
            text(x + 20, y + 38, sector, 14, MUTED, 800, family=MONO),
            text(x + 20, y + 84, value, 38, INK, 900, family=BLACK_SANS),
            text(x + 20, y + 112, f"{label.upper()}  ·  {sub}", 12, MUTED, 700, family=MONO),
        ]
    return "\n    ".join(parts), y + 130 + 40


def speed_trace(weeks: list[dict]) -> tuple[str, int]:
    """Telemetry-style line chart: contributions per week (speed) and active days per week (throttle)."""
    parts = [section_header("Speed Trace")]
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
    parts.append(f'<polygon points="{x0},{py(0):.1f} {points} {x1},{py(0):.1f}" fill="{INK}" fill-opacity="0.10"/>')
    parts.append(f'<polyline points="{points}" fill="none" stroke="{INK}" stroke-width="3" stroke-linejoin="round"/>')
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
    parts = [section_header("Timing Tower")]
    y0, row = HEAD + 10, 34
    langs = stats["languages"]
    for i, lang in enumerate(langs):
        y = y0 + i * row
        interval = "LEADER" if i == 0 else f'+{langs[i - 1]["percent"] - lang["percent"]:.1f}%'
        parts += [
            f'<rect x="{MARGIN}" y="{y}" width="560" height="{row - 4}" fill="{CARD_BG if i % 2 == 0 else PAPER2}"/>',
            f'<rect x="{MARGIN}" y="{y}" width="36" height="{row - 4}" fill="{DARK}"/>',
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
    parts.append(panel(cx, y0, cw, ch))
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
    parts = [section_header("Tyre Strategy")]
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
        stripe = colour
        for item, nw in zip(cat["items"], natural):
            w = nw * factor
            icon = (f'<path d="{item["icon"]}" fill="{ink_safe(item.get("colour", INK))}" transform="translate({x + 10:.1f},{y + 13}) scale({16 / 24})"/>'
                    if item.get("icon") else f'<rect x="{x + 13:.1f}" y="{y + 16}" width="10" height="10" fill="{item.get("colour", INK)}" transform="rotate(45 {x + 18:.1f} {y + 21})"/>')
            parts += [
                f'<rect x="{x:.1f}" y="{y + 4}" width="{w - 3:.1f}" height="34" fill="{CARD_BG}" stroke="{RULE}"/>',
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


def radio_section(messages: list[str]) -> tuple[str, int]:
    """Team radio caption, like the ones on F1 broadcasts. One message every few seconds."""
    parts = [section_header("Team Radio")]
    hold, x, y, w, h = 4, MARGIN, HEAD + 10, INNER, 92
    cycle = hold * len(messages)
    share = 1 / len(messages)
    parts += [
        panel(x, y, w, h),
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
    parts = [section_header("Race Track")]
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


GRADE_FILL = {"S": 1.0, "A+": 0.95, "A": 0.88, "A-": 0.82, "B+": 0.76, "B": 0.70, "B-": 0.64, "C+": 0.58, "C": 0.52}
LIGHT = "#9AA6C8"                                   # soft blue-grey for labels on the navy panel


def status_section(status: dict) -> tuple[str, int]:
    """Driver Status: a navy dashboard with driver details, car performance grades and race modes."""
    parts = [section_header("Driver Status")]
    top = HEAD + 10
    left, right = MARGIN + 32, MARGIN + 560
    body = []
    body.append(text(left, top + 44, "[!]", 15, YELLOW, 800, family=MONO)
                + text(left + 34, top + 44, status["banner_message"], 15, CAN, 600, family=MONO))
    body.append(f'<rect x="{MARGIN + 20}" y="{top + 64}" width="{INNER - 40}" height="1" fill="{WHITE}" opacity="0.15"/>')

    def label(x, y, title):
        return (f'<rect x="{x}" y="{y - 10}" width="9" height="9" fill="none" stroke="{YELLOW}" stroke-width="1.8" transform="rotate(45 {x + 4.5} {y - 5.5})"/>'
                + text(x + 20, y, title, 14, YELLOW, 800, family=MONO, extra='letter-spacing="4"')
                + f'<rect x="{x}" y="{y + 12}" width="{460 if x == left else W - MARGIN - 32 - x}" height="1" fill="{WHITE}" opacity="0.2"/>')

    # driver details
    y = top + 106
    body.append(label(left, y, "DRIVER"))
    for i, (key, value) in enumerate(status["driver"]):
        ry = y + 48 + i * 38
        colour = RED if key == "NUMBER" else (YELLOW if key == "ROLE" else CAN)
        body.append(text(left + 4, ry, key, 13, LIGHT, 700, family=MONO, extra='letter-spacing="2"'))
        body.append(text(left + 140, ry, value, 16, colour, 800 if key in ("NUMBER", "ROLE") else 600, family=MONO))
    gy = y + 48 + len(status["driver"]) * 38 + 14
    for i, (name, fill, note, colour) in enumerate(status["gauges"]):
        ry = gy + i * 40
        body.append(text(left + 4, ry, name, 14, colour, 900, family=MONO))
        body.append(f'<rect x="{left + 70}" y="{ry - 11}" width="220" height="10" rx="5" fill="{WHITE}" opacity="0.12"/>')
        body.append(f'<rect x="{left + 70}" y="{ry - 11}" width="{220 * fill:.0f}" height="10" rx="5" fill="{colour}"/>')
        body.append(text(left + 306, ry, note, 13, CAN, 500, family=MONO))
    left_end = gy + 40 * len(status["gauges"])

    # car performance
    body.append(label(right, y, "CAR PERFORMANCE"))
    bar_w = W - MARGIN - 32 - right - 70
    for i, row in enumerate(status["performance"]):
        ry = y + 50 + i * 56
        fill = GRADE_FILL.get(row["grade"], 0.6)
        grade_colour = YELLOW if row["grade"].startswith("A") or row["grade"] == "S" else RED
        body += [
            text(right, ry, row["area"].upper(), 15, WHITE, 900, family=MONO),
            text(right + 150, ry, row["tech"], 12, LIGHT, 600, family=MONO),
            f'<rect x="{right}" y="{ry + 10}" width="{bar_w}" height="8" rx="4" fill="{WHITE}" opacity="0.12"/>',
            f'<rect x="{right}" y="{ry + 10}" width="{bar_w * fill:.0f}" height="8" rx="4" fill="url(#perf)"/>',
            text(W - MARGIN - 36, ry + 16, row["grade"], 24, grade_colour, 900, "end", BLACK_SANS),
        ]
    right_end = y + 50 + 56 * len(status["performance"])

    # race modes
    my = max(left_end, right_end) + 30
    body.append(label(left, my, "RACE MODES").replace('width="460"', f'width="{INNER - 64}"'))
    for i, (mode, name, desc) in enumerate(status["modes"]):
        ry = my + 46 + i * 34
        colour = YELLOW if i == len(status["modes"]) - 1 else RED
        body.append(text(left + 4, ry, f"[{mode}]", 14, colour, 800, family=MONO, extra='xml:space="preserve"'))
        body.append(text(left + 150, ry, name, 15, WHITE, 900, family=MONO))
        body.append(text(left + 150 + len(name) * 9.4 + 14, ry, f"— {desc}", 14, LIGHT, 500, family=MONO))
    panel_h = my + 46 + 34 * len(status["modes"]) + 10 - top
    parts.append(panel(MARGIN, top, INNER, panel_h, 8))
    parts.append(f'<rect x="{MARGIN}" y="{top}" width="8" height="{panel_h}" fill="{RED}"/>')
    parts += body
    return "\n    ".join(parts), top + panel_h + 30


TROPHY_ICONS = {  # 24x24 line icons drawn for this profile
    "trophy": "M7 4h10v4a5 5 0 0 1-10 0z M7 6H4a3 3 0 0 0 3 4 M17 6h3a3 3 0 0 1-3 4 M12 13v4 M8 20h8 M9 17h6",
    "stopwatch": "M12 21a8 8 0 1 0 0-16 8 8 0 0 0 0 16z M12 9v4l3 2 M10 2h4 M12 2v3",
    "headset": "M4 14v-2a8 8 0 0 1 16 0v2 M4 14h3v5H4z M17 14h3v5h-3z M20 19a4 4 0 0 1-4 3h-3",
    "chart": "M4 20h16 M6 16l4-5 3 3 5-7 M18 7h-3 M18 7v3",
    "flag": "M5 21V4 M5 4h13l-2 4 2 4H5",
    "moon": "M20 14a8 8 0 1 1-10-10 7 7 0 0 0 10 10z M17 3l.6 1.4L19 5l-1.4.6L17 7l-.6-1.4L15 5l1.4-.6z",
}


def trophy_section(trophies: list[dict]) -> tuple[str, int]:
    """Trophy Cabinet: glowing hexagon badges, one per specialty."""
    parts = [section_header("Trophy Cabinet")]
    count = len(trophies)
    slot = INNER / count
    cy = HEAD + 96
    for i, t in enumerate(trophies):
        cx = MARGIN + slot * i + slot / 2
        hexagon = " ".join(f"{cx + r * __import__('math').cos(__import__('math').radians(a)):.1f},{cy + r * __import__('math').sin(__import__('math').radians(a)):.1f}"
                           for r in (56,) for a in range(-90, 270, 60))
        outer = " ".join(f"{cx + 66 * __import__('math').cos(__import__('math').radians(a)):.1f},{cy + 66 * __import__('math').sin(__import__('math').radians(a)):.1f}"
                         for a in range(-90, 270, 60))
        parts += [
            f'<polygon points="{outer}" fill="none" stroke="{t["colour"]}" stroke-width="1.5" stroke-dasharray="4 6" opacity="0.7">'
            f'<animateTransform attributeName="transform" type="rotate" from="0 {cx:.1f} {cy}" to="360 {cx:.1f} {cy}" dur="30s" repeatCount="indefinite"/></polygon>',
            f'<polygon points="{hexagon}" fill="{PANEL}" stroke="{t["colour"]}" stroke-width="4" filter="url(#glow)"/>',
            f'<path d="{TROPHY_ICONS[t["icon"]]}" fill="none" stroke="{WHITE}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" '
            f'transform="translate({cx - 24:.1f},{cy - 24}) scale(2)"/>',
            text(cx, cy + 102, t["name"], 16, INK, 900, "middle"),
            f'<rect x="{cx - 24:.1f}" y="{cy + 112}" width="48" height="3" fill="{t["colour"]}"/>',
            text(cx, cy + 136, t["tech"], 12, MUTED, 700, "middle", MONO),
        ]
    return "\n    ".join(parts), cy + 136 + 44


def spinning_tyre(cx: float, cy: float, colour: str = RED, r: int = 18) -> str:
    """A tyre seen side-on, spinning: black tyre, coloured compound band, silver rim spokes."""
    spokes = "".join(f'<rect x="-1.5" y="{-r + 9}" width="3" height="{r - 9}" fill="#B8BCC8" transform="rotate({a})"/>' for a in range(0, 360, 72))
    return (f'<g transform="translate({cx},{cy})"><g>'
            f'<circle r="{r}" fill="{DARK}"/>'
            f'<circle r="{r - 5}" fill="none" stroke="{colour}" stroke-width="3" stroke-dasharray="14 6"/>'
            f'<circle r="{r - 9}" fill="#2A2A2E"/>{spokes}<circle r="3.5" fill="{YELLOW}"/>'
            f'<animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="1.4s" repeatCount="indefinite"/></g></g>')


def tyre_divider(colour: str) -> tuple[str, int]:
    """Divider between sections: a thin track line with a spinning tyre in the middle."""
    y = 30
    return (f'<rect x="{MARGIN + 80}" y="{y}" width="{INNER / 2 - 120}" height="1.5" fill="{INK}" opacity="0.5"/>'
            f'<rect x="{W / 2 + 40}" y="{y}" width="{INNER / 2 - 120}" height="1.5" fill="{INK}" opacity="0.5"/>'
            + spinning_tyre(600, y, colour)), 64


def speed_lines(height: int) -> str:
    """Thin streaks that sweep across the poster from left to right, like motion lines."""
    rng = random.Random(33)
    out = []
    for _ in range(max(8, height // 220)):
        y = rng.uniform(40, height - 40)
        width = rng.uniform(120, 300)
        colour = rng.choice([RED, WHITE, YELLOW, WHITE])
        dur = rng.uniform(1.6, 3.2)
        out.append(f'<rect x="-400" y="{y:.0f}" width="{width:.0f}" height="2" rx="1" fill="{colour}" opacity="{rng.uniform(0.18, 0.35):.2f}">'
                   f'<animate attributeName="x" from="-400" to="{W + 50}" dur="{dur:.1f}s" begin="-{rng.uniform(0, dur):.1f}s" repeatCount="indefinite"/></rect>')
    return "\n    ".join(out)


def paper_defs(height: int) -> str:
    """Filters and gradients for the aged-paper background.

    feTurbulence makes random cloud-like noise. Low-frequency noise becomes the
    grey-brown stains, high-frequency noise becomes the fine paper grain, and a
    radial gradient darkens the edges like old, smoky paper.
    """
    return f'''<filter id="stains" x="0" y="0" width="100%" height="100%">
      <feTurbulence type="fractalNoise" baseFrequency="0.006 0.009" numOctaves="4" seed="33" result="n"/>
      <feColorMatrix in="n" type="matrix" values="0 0 0 0 0.30  0 0 0 0 0.20  0 0 0 0 0.10  0 0 0 -2.6 1.45"/>
    </filter>
    <filter id="grain" x="0" y="0" width="100%" height="100%">
      <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" seed="7" result="g"/>
      <feColorMatrix in="g" type="matrix" values="0 0 0 0 0.25  0 0 0 0 0.2  0 0 0 0 0.15  0 0 0 0.9 -0.35"/>
    </filter>
    <filter id="soft" x="-5%" y="-5%" width="110%" height="110%"><feGaussianBlur stdDeviation="22"/></filter>
    <radialGradient id="vignette" cx="0.5" cy="0.5" r="0.75">
      <stop offset="0.55" stop-color="#1A1208" stop-opacity="0"/>
      <stop offset="1" stop-color="#1A1208" stop-opacity="0.65"/>
    </radialGradient>'''


def aged_paper(width: int, height: int) -> str:
    """Base paper tone, stains, grain and smoky edges, stacked in that order."""
    return (f'<rect x="18" y="18" width="{width}" height="{height}" fill="{PAPER}"/>'
            f'<rect x="18" y="18" width="{width}" height="{height}" filter="url(#stains)" opacity="0.55"/>'
            f'<rect x="18" y="18" width="{width}" height="{height}" filter="url(#grain)" opacity="0.5"/>'
            f'<rect x="18" y="18" width="{width}" height="{height}" fill="url(#vignette)"/>')


def drafting_lines(height: int) -> str:
    """Faint technical-drawing marks across the sheet, like an engineer's working drawing.

    Long construction lines, circles with crosshairs, dimension lines with arrows,
    tick marks and small handwritten-looking measurements. A fixed seed keeps the
    pattern identical between runs.
    """
    rng = random.Random(1033)
    ink = f'stroke="{INK}" fill="none"'
    out = []
    for _ in range(max(10, height // 260)):                        # long construction lines
        if rng.random() < 0.6:
            y = rng.uniform(30, height - 30)
            x1 = rng.uniform(18, 400); x2 = rng.uniform(800, W - 18)
            out.append(f'<line x1="{x1:.0f}" y1="{y:.0f}" x2="{x2:.0f}" y2="{y:.0f}" {ink} stroke-width="0.8" opacity="{rng.uniform(0.12, 0.25):.2f}"/>')
        else:
            x = rng.uniform(30, W - 30)
            y1 = rng.uniform(18, height - 600); y2 = y1 + rng.uniform(250, 600)
            out.append(f'<line x1="{x:.0f}" y1="{y1:.0f}" x2="{x:.0f}" y2="{y2:.0f}" {ink} stroke-width="0.8" opacity="{rng.uniform(0.12, 0.25):.2f}"/>')
    for _ in range(max(6, height // 600)):                         # circles with crosshairs
        cx = rng.choice([rng.uniform(40, 140), rng.uniform(W - 140, W - 40), rng.uniform(140, W - 140)])
        cy = rng.uniform(80, height - 80)
        r = rng.uniform(22, 70)
        op = rng.uniform(0.14, 0.26)
        out.append(f'<g opacity="{op:.2f}"><circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r:.0f}" {ink} stroke-width="0.9"/>'
                   f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r * 0.55:.0f}" {ink} stroke-width="0.7" stroke-dasharray="3 4"/>'
                   f'<line x1="{cx - r * 1.4:.0f}" y1="{cy:.0f}" x2="{cx + r * 1.4:.0f}" y2="{cy:.0f}" {ink} stroke-width="0.7"/>'
                   f'<line x1="{cx:.0f}" y1="{cy - r * 1.4:.0f}" x2="{cx:.0f}" y2="{cy + r * 1.4:.0f}" {ink} stroke-width="0.7"/></g>')
    for _ in range(max(6, height // 500)):                         # dimension lines with arrows and a measurement
        y = rng.uniform(60, height - 60)
        x1 = rng.uniform(30, W / 2); x2 = x1 + rng.uniform(120, 360)
        op = rng.uniform(0.18, 0.3)
        out.append(f'<g opacity="{op:.2f}"><path d="M{x1:.0f},{y - 7:.0f} V{y + 7:.0f} M{x2:.0f},{y - 7:.0f} V{y + 7:.0f} M{x1:.0f},{y:.0f} H{x2:.0f}" {ink} stroke-width="0.8"/>'
                   f'<path d="M{x1 + 7:.0f},{y - 3:.0f} L{x1:.0f},{y:.0f} L{x1 + 7:.0f},{y + 3:.0f} M{x2 - 7:.0f},{y - 3:.0f} L{x2:.0f},{y:.0f} L{x2 - 7:.0f},{y + 3:.0f}" {ink} stroke-width="0.8"/>'
                   f'<text x="{(x1 + x2) / 2:.0f}" y="{y - 5:.0f}" text-anchor="middle" font-family="\'Courier New\',monospace" font-size="10" '
                   f'font-style="italic" fill="{INK}">{rng.choice(["R 340", "Ø 120", "12.5", "3600", "H 950", "A-A", "2000", "45°", "1:25"])}</text></g>')
    for _ in range(max(12, height // 200)):                        # small tick clusters and handwritten notes
        x = rng.uniform(24, W - 60); y = rng.uniform(30, height - 30)
        op = rng.uniform(0.15, 0.28)
        ticks = "".join(f'<line x1="{x + i * 5:.0f}" y1="{y:.0f}" x2="{x + i * 5:.0f}" y2="{y + (6 if i % 5 else 11):.0f}" {ink} stroke-width="0.7"/>' for i in range(rng.randint(6, 14)))
        note = rng.choice(["fig. 3", "sect. B", "ref 7", "tol ±0.2", "detail C", "scale 1:10", "v2", "rev. 4"])
        out.append(f'<g opacity="{op:.2f}">{ticks}<text x="{x:.0f}" y="{y - 4:.0f}" font-family="\'Courier New\',monospace" font-size="10" font-style="italic" fill="{INK}">{note}</text></g>')
    return "\n    ".join(out)


# --------------------------------------------------------------------------
# Whole poster
# --------------------------------------------------------------------------
def build_profile(content: dict, days: dict, streaks: dict, stats: dict, snake_svg: str, today: dt.date) -> str:
    profile = content["profile"]
    sections = [
        poster_top(profile, streaks, stats),
        status_section(content["status"]),
        trophy_section(content["trophies"]),
        sector_section(streaks, today),
        speed_trace(weekly_contributions(days, today)),
        tower_section(stats),
        strategy_section(content["tech_stack"]),
        radio_section(content["radio_messages"]),
        track_section(snake_svg),
    ]
    tyre_colours = [RED, YELLOW, RED, YELLOW]
    blocks, y = [], 0
    for n, (body, height) in enumerate(sections):
        blocks.append(f'<g transform="translate(0,{y})">\n    {body}\n    </g>')
        y += height
        if 1 <= n < len(sections) - 1:                     # spinning tyre between the data sections
            divider, dh = tyre_divider(tyre_colours[n % len(tyre_colours)])
            blocks.append(f'<g transform="translate(0,{y - 20})">{divider}</g>')
            y += dh - 20
    foot = y + 10
    blocks.append(f'<rect x="{MARGIN}" y="{foot}" width="{INNER}" height="1.2" fill="{INK}"/>')
    blocks.append(text(MARGIN, foot + 28, f"{profile['first_name']} {profile['last_name']}  ·  #{profile['race_number']}", 12, INK, 800, family=MONO))
    blocks.append(spinning_tyre(W - MARGIN - 18, foot + 24, RED, 14))
    paper_h = foot + 60
    height = paper_h + 36                          # black poster frame around the paper

    grade, _ = rank(stats)
    status = content["status"]
    label = (f'{profile["first_name"]} {profile["last_name"]}, number {profile["race_number"]}. {" | ".join(profile["roles"])}. '
             + "Car performance: " + ", ".join(f'{r["area"]} {r["grade"]}' for r in status["performance"]) + ". "
             + "Trophies: " + ", ".join(t["name"] for t in content["trophies"]) + ". "
             + f'{streaks["total"]} total contributions, longest streak {streaks["longest"]["length"]} days, power level {grade}. '
             + "Tech stack: " + " ".join(f'{c["category"]}: {", ".join(i["label"] for i in c["items"])}.' for c in content["tech_stack"]))
    joined = "\n    ".join(blocks)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height}" width="{W}" height="{height}" role="img" aria-label="{esc(label)}">
  <title>{esc(label)}</title>
  <style>@media (prefers-reduced-motion: reduce) {{ .fx {{ display: none; }} }}</style>
  <defs>
    {paper_defs(height)}
    <linearGradient id="perf" x1="0" x2="1"><stop offset="0" stop-color="{YELLOW}"/><stop offset="1" stop-color="{RED}"/></linearGradient>
    <filter id="glow" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    <clipPath id="paper"><rect x="18" y="18" width="{W - 36}" height="{paper_h}"/></clipPath>
  </defs>
  <rect width="{W}" height="{height}" rx="6" fill="#1A1A1A"/>
  {aged_paper(W - 36, paper_h)}
  <g clip-path="url(#paper)">
    <g>
    {drafting_lines(height)}
    </g>
    <g class="fx">
    {speed_lines(height)}
    </g>
    <g transform="translate(0,18)">
    {joined}
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
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    svg = build_profile(content, days, streaks, stats, SNAKE_FILE.read_text(encoding="utf-8"), today)
    (OUT_DIR / "profile.svg").write_text(svg, encoding="utf-8")
    print(f'Wrote {OUT_DIR}/profile.svg (total {streaks["total"]}, grade {rank(stats)[0]})')


if __name__ == "__main__":
    main()
