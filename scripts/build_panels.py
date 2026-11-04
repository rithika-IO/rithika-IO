#!/usr/bin/env python3
"""Build the mission-control profile image for the profile README.

Run by .github/workflows/snake.yml after the snake has been generated.

Why this script exists
----------------------
An SVG shown in a README cannot load other images or run JavaScript, so live
stat cards cannot be placed inside a themed layout. This script instead reads
the numbers from the GitHub API and hands them to dashboard.py, which draws
every panel into ONE self-contained SVG (the car photo is embedded too).

The split:
    build_panels.py   data: GitHub API calls, streaks, grade, recent activity
    dashboard.py      presentation: turns that data into SVG

Inputs
    GITHUB_TOKEN                  token for the GitHub API (provided by GitHub Actions)
    GH_USER                       GitHub login to read statistics for
    OUT_DIR                       folder holding github-snake-dark.svg; output goes here
    DISPLAY_TZ                    time zone for times shown on the image (default Asia/Colombo)
    scripts/profile_content.json  name, number, callouts, trophies, tech stack and radio messages
    assets/car-top.jpg            top-down car photo, embedded in the image

Output
    OUT_DIR/profile.svg

Only the Python standard library is used, so the workflow needs no install step.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

import dashboard

LOGIN = os.environ.get("GH_USER", "rithika-IO")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUT_DIR = Path(os.environ.get("OUT_DIR", "dist"))
DISPLAY_TZ = ZoneInfo(os.environ.get("DISPLAY_TZ", "Asia/Colombo"))
SNAKE_FILE = OUT_DIR / "github-snake-dark.svg"
CONTENT_FILE = Path(__file__).with_name("profile_content.json")


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
        repo["language_sizes"] = rest(f"/repos/{repo['full_name']}/languages")
        for name, size in repo["language_sizes"].items():
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
        "repos": repos,
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
# Repo showcase: one card per public repo, shown at the cockpit marker
# --------------------------------------------------------------------------
# Checked in order; the first rule whose keywords appear in a repo's description,
# topics or languages decides its project type. profile_content.json can override
# any repo by name (repo_showcase.types), so a wrong guess is a one-line fix.
TYPE_RULES = [
    ("Machine learning", ("machine learning", "machine-learning", " ml ", "prediction", "predict", "classifier",
                          "scikit", "pytorch", "tensorflow", "distilbert", "nlp", "anomaly", "jupyter notebook")),
    ("Enterprise app",   ("spring boot", "spring-boot", "javafx", "asp.net", "enterprise", "management system", "insurance")),
    ("Full-stack",       ("full-stack", "full stack", "fullstack")),
    ("Language tooling", ("interpreter", "compiler", "parser", "lexer", "programming language")),
    ("CLI tool",         (" cli ", " cli,", "command-line", "command line", "terminal", "process manager")),
    ("Backend service",  (" api ", "backend", "microservice", "gateway", "queue", "worker")),
    ("Frontend",         ("portfolio", "website", "landing page")),
]


def time_ago(then: dt.datetime, now: dt.datetime) -> str:
    seconds = max(0, int((now - then).total_seconds()))
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if seconds >= size:
            return f"{seconds // size}{unit} ago"
    return "just now"


def project_type(repo: dict, overrides: dict) -> str:
    """Guess what kind of project a repo is, unless profile_content.json says so."""
    if repo["name"] in overrides:
        return overrides[repo["name"]]
    languages = [name.lower() for name in repo.get("language_sizes", {})]
    words = f' {(repo.get("description") or "").lower()} {" ".join(repo.get("topics") or [])} {" ".join(languages)} '
    words = words.replace(".", " ").replace("(", " ").replace(")", " ")
    for name, keywords in TYPE_RULES:
        if any(k in words for k in keywords):
            return name
    frontend = {"typescript", "javascript", "css", "html"} & set(languages)
    backend = {"python", "java", "go", "c#", "php", "plpgsql"} & set(languages)
    return "Full-stack" if frontend and backend else "Project"


SUPPORT_LANGUAGES = {"CSS", "HTML", "SCSS", "Shell", "PowerShell", "Batchfile", "Makefile", "Dockerfile", "Procfile"}
SHORT_NAMES = {"Jupyter Notebook": "Jupyter"}


def stack_of(repo: dict) -> str:
    """The repo's top two languages by bytes of code, e.g. "TypeScript · Python".

    Styling and build files (CSS, Shell, Dockerfile...) only count when there is
    nothing else, so a JavaFX app reads "Java", not "Java · CSS".
    """
    ranked = [name for name, _ in sorted(repo.get("language_sizes", {}).items(), key=lambda kv: kv[1], reverse=True)]
    main = [name for name in ranked if name not in SUPPORT_LANGUAGES] or ranked
    return " · ".join(SHORT_NAMES.get(name, name) for name in main[:2]) or repo.get("language") or "Mixed"


def repo_cards(repos: list[dict], settings: dict, now: dt.datetime) -> list[dict]:
    """Callout cards for every public repo, most recently pushed first.

    Skipped: the profile repo (the workflow commits to it twice a day), archived
    repos, and any names listed in repo_showcase.hide.
    """
    hidden = {name.lower() for name in settings.get("hide", [])} | {LOGIN.lower()}
    overrides = settings.get("types", {})
    shown = [r for r in repos if r.get("name", "").lower() not in hidden and not r.get("archived") and r.get("pushed_at")]
    shown.sort(key=lambda r: r["pushed_at"], reverse=True)
    if settings.get("limit"):
        shown = shown[:settings["limit"]]
    cards = []
    for repo in shown:
        pushed = dt.datetime.fromisoformat(repo["pushed_at"].replace("Z", "+00:00"))
        kind = project_type(repo, overrides)
        cards.append({"spot": "cockpit", "title": repo["name"], "kind": kind,
                      "rows": [[kind, "project type"], [stack_of(repo), "stack"],
                               [f'★ {repo.get("stargazers_count", 0)} · {time_ago(pushed, now)}', "stars · last push"]]})
    return cards


# --------------------------------------------------------------------------
# Data for the dashboard panels
# --------------------------------------------------------------------------
def recent_daily(days: dict[dt.date, int], today: dt.date, count: int = 60) -> list[int]:
    """Contributions per day for the last `count` days, oldest first (Engine load chart)."""
    return [days.get(today - dt.timedelta(days=offset), 0) for offset in range(count - 1, -1, -1)]


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {many or word + 's'}"


def describe_event(event: dict) -> tuple[str, str] | None:
    """Map one public event to (kind, status text) for System logs, or None to skip it.

    Since late 2025 GitHub no longer includes commit counts in PushEvent
    payloads, so pushes are counted per event instead of per commit.
    """
    kind, payload = event.get("type"), event.get("payload") or {}
    if kind == "PushEvent":
        return "push", "1 push"
    if kind == "PullRequestEvent":
        action = payload.get("action", "")
        merged = (payload.get("pull_request") or {}).get("merged")
        return "pr", "PR merged" if action == "closed" and merged else f"PR {action}".strip()
    if kind == "CreateEvent":
        ref = payload.get("ref_type", "")
        return ("create", "new repo") if ref == "repository" else ("create", f"new {ref}") if ref in ("branch", "tag") else None
    if kind == "IssuesEvent":
        return "issue", f'issue {payload.get("action", "")}'.strip()
    if kind == "WatchEvent":
        return "star", "starred"
    if kind == "ReleaseEvent":
        return "create", "release"
    return None


def fetch_events(now: dt.datetime, limit: int = 4) -> list[dict]:
    """The latest public activity, newest first, with back-to-back pushes to one repo merged.

    This panel is a nice-to-have, so any API failure gives an empty list
    (the panel then says "no recent activity") instead of failing the build.
    """
    try:
        raw = rest(f"/users/{LOGIN}/events/public?per_page=50")
    except (urllib.error.URLError, ValueError) as exc:
        print("Recent activity unavailable:", exc, file=sys.stderr)
        return []
    rows: list[dict] = []
    for event in raw if isinstance(raw, list) else []:
        described = describe_event(event)
        if not described:
            continue
        kind, status = described
        repo = (event.get("repo") or {}).get("name", "").split("/")[-1]
        when = dt.datetime.fromisoformat(event["created_at"].replace("Z", "+00:00")).astimezone(DISPLAY_TZ)
        last = rows[-1] if rows else None
        if last and kind == "push" and last["kind"] == "push" and last["repo"] == repo:
            last["pushes"] += 1
            last["status"] = plural(last["pushes"], "push", "pushes")
            continue
        if len(rows) == limit:
            break
        same_day = when.date() == now.astimezone(DISPLAY_TZ).date()
        rows.append({"time": when.strftime("%H:%M") if same_day else when.strftime("%b %d"),
                     "repo": repo, "kind": kind, "status": status, "pushes": 1})
    return rows


def sync_label(now: dt.datetime) -> str:
    """When this image was built, e.g. 2026-11-04 10:00 UTC+05:30."""
    local = now.astimezone(DISPLAY_TZ)
    offset = local.strftime("%z")
    return f"{local:%Y-%m-%d %H:%M} UTC{offset[:3]}:{offset[3:]}"


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def main() -> None:
    if not TOKEN:
        sys.exit("GITHUB_TOKEN is not set")
    if not SNAKE_FILE.exists():
        sys.exit(f"{SNAKE_FILE} not found; the snake must be generated before this script runs")
    content = json.loads(CONTENT_FILE.read_text(encoding="utf-8"))
    now = dt.datetime.now(dt.timezone.utc)
    today = now.date()

    days = fetch_contribution_days()
    streaks = compute_streaks(days, today)
    stats = fetch_stats()
    grade, percentile = rank(stats)
    content["repo_cards"] = repo_cards(stats["repos"], content.get("repo_showcase", {}), now)
    year_total = sum(days.get(today - dt.timedelta(days=offset), 0) for offset in range(365))

    svg = dashboard.build(
        content, stats, streaks, grade, percentile,
        daily=recent_daily(days, today),
        year_total=year_total,
        events=fetch_events(now),
        snake_svg=SNAKE_FILE.read_text(encoding="utf-8"),
        synced=sync_label(now),
        login=LOGIN,
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "profile.svg").write_text(svg, encoding="utf-8")
    print(f'Wrote {OUT_DIR}/profile.svg ({len(svg) // 1024} KB, total {streaks["total"]}, grade {grade})')


if __name__ == "__main__":
    main()
