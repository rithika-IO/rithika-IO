#!/usr/bin/env python3
"""The Engineer's Codex: draws the profile as pages from a Renaissance notebook.

Presentation only, like dashboard.py: build_panels.py fetches the data and calls
build(). Every picture is a public-domain artwork (see CREDITS.md), prepared once
and kept in assets/codex/. They are embedded as data URIs because a README SVG
cannot load anything from outside itself. Line drawings are stored as grayscale
masks (white = ink), so they can be inked in any colour from the palette.

Sections, top to bottom:
    header       The Creation of Adam hands, RW monogram, name
    motto        Greek proverb with its meaning
    offerings    six stats, each beside a Doric column
    proportions  Vitruvian Man; a note card circles the limbs (skills) and the
                 centre (one repo per lap)
    astrolabes   three dials: works this year, unbroken days, standing
    tongues | persona
    flight       Goltzius's Icarus, 60 days of work, the sun over the fullest day
    dispatches   recent public activity
    oracle       rotating lines between the Heath engraving and the Euphronios krater
    laurels      trophies as laurel wreaths
    workshop     the tech stack, one shield per tool
    ouroboros    the past year as a ring, with the serpent eating its tail
"""
from __future__ import annotations

import base64
import datetime as dt
import math
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "codex"
BRAND_MARK = ASSETS.parent / "rw-mark.png"

W = 900
MARGIN = 60
GAP = 24
HALF = (W - 2 * MARGIN - GAP) / 2                            # two folios side by side

PARCH, PARCH_DARK = "#E9DFC7", "#DFD2B4"
INK, SEPIA, GOLD, CHALK = "#3B2F23", "#7A5230", "#C9A227", "#A3412E"
DEEP_INK = "#1C1611"

SERIF = "Cinzel, 'Trajan Pro', Georgia, serif"
BODY = "Georgia, 'Times New Roman', serif"
GREEK = "Cardo, 'GFS Didot', Georgia, serif"
MONO = "'SFMono-Regular', Menlo, Consolas, monospace"

STEP = 4.0                                                   # seconds per note card at the Vitruvian figure
NUMERALS = "I II III IV V VI VII VIII IX X XI XII".split()


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def esc(value) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def data_uri(name: str, kind: str) -> str:
    path = BRAND_MARK if name == "rw-mark.png" else ASSETS / name
    return f"data:{kind};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def t(x, y, s, size, fill=INK, family=BODY, weight=400, anchor="start", extra="") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}" {extra}>{esc(s)}</text>')


def caps(x, y, s, size=10, fill=SEPIA, anchor="start") -> str:
    return t(x, y, str(s).upper(), size, fill, SERIF, 600, anchor, 'letter-spacing="2.2"')


def italic(x, y, s, size=14, fill=SEPIA, anchor="start") -> str:
    return t(x, y, s, size, fill, BODY, 400, anchor, 'font-style="italic"')


def shorten(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[:limit - 1] + "…"


def wrap(content: str, width: int) -> list[str]:
    lines, line = [], ""
    for word in content.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + [line] if line else lines


def inked(mask_id: str, w: int, h: int, x: float, y: float, scale: float = 1, fill: str = INK, opacity: float = 1) -> str:
    """Paint a line drawing: a rectangle of ink shown only through the drawing's mask."""
    return (f'<rect x="0" y="0" width="{w}" height="{h}" fill="{fill}" opacity="{opacity}" mask="url(#{mask_id})" '
            f'transform="translate({x:.1f},{y:.1f}) scale({scale:.4f})"/>')


def rule(y: float) -> str:
    """Double ink rule with a red chalk diamond, like a manuscript divider."""
    mid = W / 2
    return (f'<path d="M{MARGIN},{y} H{mid - 14} M{mid + 14},{y} H{W - MARGIN} M{MARGIN},{y + 4} H{mid - 14} M{mid + 14},{y + 4} H{W - MARGIN}" '
            f'stroke="{SEPIA}" stroke-width="0.8" opacity="0.7"/>'
            f'<path d="M{mid},{y - 5} l7,7 l-7,7 l-7,-7 Z" fill="{CHALK}" opacity="0.85"/>')


def frame(x, y, w, h, title, subtitle="") -> str:
    """A manuscript panel: thin double border and a Cinzel title."""
    out = [f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{PARCH_DARK}" fill-opacity="0.45" stroke="{SEPIA}" stroke-width="0.9"/>',
           f'<rect x="{x + 5:.1f}" y="{y + 5:.1f}" width="{w - 10:.1f}" height="{h - 10:.1f}" fill="none" stroke="{SEPIA}" stroke-width="0.5" opacity="0.6"/>',
           t(x + 24, y + 50, title, 22, INK, SERIF, 600)]
    if subtitle:
        out.append(italic(x + 24, y + 74, subtitle, 13))
    return "".join(out)


def timed_opacity(i: int, n: int, step: float, fade_s: float = 0.5) -> str:
    """Visible only during slot i of n in one shared loop (SMIL keyTimes are fractions of the loop)."""
    a, b = i / n, (i + 1) / n
    f = fade_s / (n * step)
    if i == 0:
        times, vals = [0, b - f, b, 1], [1, 1, 0, 0]
    else:
        times, vals = [0, a, a + f, b - f, b, 1], [0, 0, 1, 1, 0, 0]
    return (f'<animate attributeName="opacity" dur="{n * step}s" repeatCount="indefinite" '
            f'keyTimes="{";".join(f"{v:.4f}" for v in times)}" values="{";".join(map(str, vals))}"/>')


def windows_opacity(slots: list[int], n: int, step: float, fade_s: float = 0.5) -> str:
    """Like timed_opacity, but visible in several slots of the loop. Lets one card or
    line be reused every lap instead of repeating the same markup for each lap."""
    f = fade_s / (n * step)
    times, vals = [0.0], [1 if 0 in slots else 0]
    for i in sorted(slots):
        a, b = i / n, (i + 1) / n
        if i == 0:
            times += [b - f, b]
            vals += [1, 0]
        else:
            times += [a, a + f, b - f, b]
            vals += [0, 1, 1, 0]
    times.append(1.0)
    vals.append(vals[-1] if 0 not in slots else 0)
    return (f'<animate attributeName="opacity" dur="{n * step}s" repeatCount="indefinite" '
            f'keyTimes="{";".join(f"{v:.4f}" for v in times)}" values="{";".join(map(str, vals))}"/>')


def polar(cx, cy, r, deg):
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def arc(cx, cy, r, d0, d1) -> str:
    """Clockwise arc path from angle d0 to d1 (degrees, 0 = 3 o'clock)."""
    x0, y0 = polar(cx, cy, r, d0)
    x1, y1 = polar(cx, cy, r, d1)
    large = 1 if (d1 - d0) % 360 > 180 else 0
    return f"M{x0:.1f},{y0:.1f} A{r},{r} 0 {large} 1 {x1:.1f},{y1:.1f}"


# --------------------------------------------------------------------------
# Header and motto
# --------------------------------------------------------------------------
def header(content: dict) -> tuple[str, int]:
    hh = 309                                                 # the hands image is 900 x 309
    gap_x, gap_y = 477 / 1000 * W, 160 / 343 * hh           # the space between the two fingertips
    mark_w = 38
    mark_h = mark_w * 88 / 144
    profile = content["profile"]
    return (f'<image href="{data_uri("hands.jpg", "image/jpeg")}" x="0" y="0" width="{W}" height="{hh}" mask="url(#handsfade)"/>'
            # the monogram floats just above the gap between the fingertips
            f'<rect x="0" y="0" width="144" height="88" fill="{DEEP_INK}" mask="url(#rwmask)" '
            f'transform="translate({gap_x - mark_w / 2:.1f},{gap_y - mark_h - 16:.1f}) scale({mark_w / 144:.4f})"/>'
            + t(W / 2, hh + 40, profile["full_name"].upper(), 38, INK, SERIF, 600, "middle", 'letter-spacing="6"')
            + caps(W / 2, hh + 68, content["codex"]["subtitle"], 10.5, CHALK, "middle")), hh + 92


def motto(y: float, m: dict) -> tuple[str, int]:
    return (rule(y + 4)
            + t(W / 2, y + 66, m["greek"], 40, INK, GREEK, 400, "middle", 'letter-spacing="1.5"')
            + italic(W / 2, y + 96, m["english"], 16, SEPIA, "middle")
            + caps(W / 2, y + 120, m["source"], 9, SEPIA, "middle")
            + rule(y + 142)), 166


# --------------------------------------------------------------------------
# Offerings: the six stats
# --------------------------------------------------------------------------
def doric_column(x, y, w, h) -> str:
    flutes = "".join(f'<path d="M{x + w * f:.1f},{y + 10} V{y + h - 8}" stroke="{SEPIA}" stroke-width="0.6" opacity="0.7"/>' for f in (0.3, 0.5, 0.7))
    return (f'<rect x="{x - 4}" y="{y}" width="{w + 8}" height="5" fill="{INK}"/>'
            f'<path d="M{x},{y + 5} H{x + w} L{x + w - 3},{y + 10} H{x + 3} Z" fill="{INK}"/>'
            f'<rect x="{x + 3}" y="{y + 10}" width="{w - 6}" height="{h - 18}" fill="none" stroke="{INK}" stroke-width="1"/>{flutes}'
            f'<rect x="{x - 2}" y="{y + h - 8}" width="{w + 4}" height="4" fill="{INK}"/><rect x="{x - 5}" y="{y + h - 4}" width="{w + 10}" height="4" fill="{INK}"/>')


def offerings(y: float, stats: dict, streaks: dict, grade: str) -> tuple[str, int]:
    tiles = [("Commits", f'{stats["commits"]:,}'), ("Stars", f'{stats["stars"]:,}'), ("Pull requests", f'{stats["prs"]:,}'),
             ("Streak", f'{streaks["current"]["length"]} / {streaks["longest"]["length"]}'), ("Mastery", grade),
             ("Works", f'{streaks["total"]:,}')]
    gap = 12
    tw = (W - 2 * MARGIN - gap * 5) / 6
    out = []
    for i, (name, value) in enumerate(tiles):
        x = MARGIN + i * (tw + gap)
        out += [doric_column(x + 10, y + 6, 16, 70), t(x + 36, y + 42, value, 20, INK, SERIF, 600), caps(x + 36, y + 62, name, 8.5)]
    return "".join(out), 92


# --------------------------------------------------------------------------
# The Proportions: Vitruvian Man with a note card that circles the figure
# --------------------------------------------------------------------------
# Points on the 480 x 600 drawing. The card visits the limbs in a circle, then the
# centre, where each lap shows the next repo.
SPOTS = {"front_left": (78, 157), "front_right": (402, 157), "rear_left": (134, 486), "rear_right": (348, 482), "cockpit": (240, 292)}


def note_sequence(skills: list[dict], repos: list[dict]) -> list[dict]:
    """One lap per repo: the four limbs, then the centre with the next repo."""
    if not repos or not skills:
        return skills or repos
    return [card for repo in repos for card in (*skills, repo)]


def proportions(y: float, content: dict) -> tuple[str, int]:
    h = 660
    codex = content["codex"]
    fx, fy = W - MARGIN - 480, y + 30
    point = lambda key: (fx + SPOTS[key][0], fy + SPOTS[key][1])
    skill_labels, repo_labels = codex["skill_row_labels"], codex["repo_row_labels"]
    skills = [dict(c, rows=[[v, skill_labels[i] if i < len(skill_labels) else n] for i, (v, n) in enumerate(c["rows"])])
              for c in content["car_callouts"]]
    repos = [dict(c, rows=[[v, repo_labels[i] if i < len(repo_labels) else n] for i, (v, n) in enumerate(c["rows"])])
             for c in content.get("repo_cards", [])]
    slots = note_sequence(skills, repos)

    parts = [inked("flyermask", 330, 288, 30, y + 160, 1, SEPIA, 0.14),
             inked("drillmask", 130, 172, 170, y + 470, 1, SEPIA, 0.13),
             t(MARGIN, y + 46, codex["proportions_title"][0], 30, INK, SERIF, 600),
             t(MARGIN, y + 80, codex["proportions_title"][1], 30, INK, SERIF, 600),
             italic(MARGIN, y + 110, codex["proportions_subtitle"]),
             inked("vitmask", 480, 600, fx, fy)]
    for key in SPOTS:
        sx, sy = point(key)
        parts.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="7" fill="none" stroke="{CHALK}" stroke-width="1.4">'
                     f'<animate attributeName="r" values="7;15;7" dur="2.6s" repeatCount="indefinite"/>'
                     f'<animate attributeName="opacity" values="0.9;0;0.9" dur="2.6s" repeatCount="indefinite"/></circle>'
                     f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="4.5" fill="{CHALK}" stroke="{PARCH}" stroke-width="1.5"/>')
    if not slots:
        return "".join(parts), h

    n = len(slots)
    cx, cw, ch = MARGIN, 252, 236
    card_ys = []
    for c in slots:
        sx, sy = point(c["spot"])
        card_ys.append(min(max(sy - ch / 2, y + 140), y + h - ch - 10))
    for key in SPOTS:
        at_spot = [i for i, c in enumerate(slots) if c["spot"] == key]
        if not at_spot:
            continue
        sx, sy = point(key)
        parts.append(f'<g opacity="{1 if 0 in at_spot else 0}">{windows_opacity(at_spot, n, STEP)}'
                     f'<path d="M{cx + cw + 4},{sy:.0f} H{sx - 12:.0f}" stroke="{CHALK}" stroke-width="1" stroke-dasharray="2 4"/>'
                     f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="11" fill="none" stroke="{INK}" stroke-width="1.4"/></g>')
    keys, vals = [], []
    for i in range(n):
        keys += [i / n, (i + 1) / n - 0.5 / (n * STEP)]
        vals += [card_ys[i], card_ys[i]]
    keys.append(1.0)
    vals.append(card_ys[0])
    slide = (f'<animateTransform attributeName="transform" type="translate" dur="{n * STEP}s" repeatCount="indefinite" '
             f'keyTimes="{";".join(f"{k:.4f}" for k in keys)}" values="{";".join(f"0,{v - card_ys[0]:.1f}" for v in vals)}"/>')
    top = card_ys[0]
    card = [f'<rect x="{cx}" y="{top:.1f}" width="{cw}" height="{ch}" fill="{PARCH_DARK}" stroke="{SEPIA}" stroke-width="1"/>',
            f'<rect x="{cx + 5}" y="{top + 5:.1f}" width="{cw - 10}" height="{ch - 10}" fill="none" stroke="{SEPIA}" stroke-width="0.6" opacity="0.6"/>']
    distinct = []                                            # (card, [slot indexes where it shows])
    for i, c in enumerate(slots):
        for known, where in distinct:
            if known is c:
                where.append(i)
                break
        else:
            distinct.append((c, [i]))
    for c, where in distinct:
        body = [caps(cx + 22, top + 32, codex["limbs"].get(c["spot"], ""), 8.5, CHALK),
                t(cx + 22, top + 64, shorten(c["title"], 17), 22, INK, SERIF, 600)]
        for r, (value, name) in enumerate(c["rows"][:3]):
            ry = top + 104 + r * 46
            value = shorten(str(value), 24)
            if r == 0 and len(value) <= 4:
                body += [t(cx + 22, ry, value, 28, CHALK, SERIF, 600), caps(cx + 30 + 18 * len(value), ry - 2, name, 8.5)]
            else:
                body += [t(cx + 22, ry, value, 16, CHALK if r == 0 else INK), caps(cx + 22, ry + 18, name, 8.5)]
        card.append(f'<g opacity="{1 if 0 in where else 0}">{windows_opacity(where, n, STEP)}{"".join(body)}</g>')
    parts.append(f'<g>{slide}{"".join(card)}</g>')
    return "".join(parts), h


# --------------------------------------------------------------------------
# The Astrolabes
# --------------------------------------------------------------------------
def astrolabe(cx, cy, r, frac, value, name, lo, hi) -> str:
    out = [f'<circle cx="{cx:.1f}" cy="{cy}" r="{r}" fill="{PARCH}" stroke="{INK}" stroke-width="1.4"/>',
           f'<circle cx="{cx:.1f}" cy="{cy}" r="{r - 7}" fill="none" stroke="{SEPIA}" stroke-width="0.6"/>']
    for k in range(25):
        a = math.radians(-225 + k * 270 / 24)
        r0 = r - (16 if k % 6 == 0 else 11)
        out.append(f'<path d="M{cx + r0 * math.cos(a):.1f},{cy + r0 * math.sin(a):.1f} L{cx + (r - 7) * math.cos(a):.1f},{cy + (r - 7) * math.sin(a):.1f}" '
                   f'stroke="{INK}" stroke-width="{1.2 if k % 6 == 0 else 0.6}"/>')
    for k, numeral in enumerate(NUMERALS[:5]):
        a = math.radians(-225 + k * 270 / 4)
        out.append(t(cx + (r - 26) * math.cos(a), cy + (r - 26) * math.sin(a) + 3, numeral, 8, SEPIA, SERIF, 600, "middle"))
    deg = -225 + 270 * max(0.0, min(1.0, frac))
    out += [f'<g transform="translate({cx:.1f},{cy})"><g><path d="M0,4 L{r - 20},0 L0,-4 Z" fill="{CHALK}"/>'
            f'<animateTransform attributeName="transform" type="rotate" values="-225;{deg + 6:.1f};{deg:.1f}" keyTimes="0;0.8;1" dur="2.4s" fill="freeze"/></g>'
            f'<circle r="5" fill="{GOLD}" stroke="{INK}"/></g>',
            t(cx, cy + r * 0.62, value, 17, INK, SERIF, 600, "middle"),
            caps(cx, cy + r + 24, name, 9, SEPIA, "middle"),
            caps(cx - r * 0.78, cy + r + 8, lo, 7.5, SEPIA, "middle"), caps(cx + r * 0.78, cy + r + 8, hi, 7.5, SEPIA, "middle")]
    return "".join(out)


def astrolabes(y: float, streaks: dict, percentile: float, year_total: int) -> tuple[str, int]:
    h = 262
    top = max(1000, math.ceil(year_total / 500) * 500)
    longest = max(streaks["longest"]["length"], 1)
    dials = [(year_total / top, f"{year_total:,}", "works this year", "0", f"{top / 1000:g}k"),
             (streaks["current"]["length"] / longest, f'{streaks["current"]["length"]} days', "unbroken days", "0", f"{longest}"),
             ((100 - percentile) / 100, f"{100 - percentile:.0f}%", "standing among peers", "0", "100")]
    out = [frame(MARGIN, y, W - 2 * MARGIN, h, "The Astrolabes")]
    for i, d in enumerate(dials):
        out.append(astrolabe(MARGIN + (W - 2 * MARGIN) / 6 * (2 * i + 1), y + 140, 62, *d))
    return "".join(out), h


# --------------------------------------------------------------------------
# Tongues and Persona
# --------------------------------------------------------------------------
HATCHES = [("hatch1", 45, 4), ("hatch2", 0, 3.5), ("hatch3", 90, 4), ("hatch4", 135, 3), ("hatch5", 45, 6), ("hatch6", 0, 6), ("hatch7", 135, 6)]


def tongues(x, y, w, h, languages: list[dict]) -> str:
    out = [frame(x, y, w, h, "Tongues", f"{len(languages)} languages spoken")]
    for i, lang in enumerate(languages[:2]):
        bx = x + 24 + i * (w - 48) / 2
        number = f'{lang["percent"]:.0f}'
        out += [t(bx, y + 140, number, 40, INK, SERIF, 600), t(bx + 27 * len(number), y + 140, "%", 16, SEPIA, SERIF, 600),
                caps(bx, y + 160, lang["name"], 9)]
    bx, bw, by = x + 24, w - 48, y + 182
    cx = bx
    for i, lang in enumerate(languages):
        seg = bw * lang["percent"] / 100
        if seg >= 1:
            out.append(f'<rect x="{cx:.1f}" y="{by}" width="{seg:.1f}" height="14" fill="url(#{HATCHES[i % len(HATCHES)][0]})" stroke="{INK}" stroke-width="0.7"/>')
            cx += seg
    for i, lang in enumerate(languages[2:7]):
        ry = y + 226 + i * 26
        out += [f'<rect x="{bx}" y="{ry - 9}" width="12" height="10" fill="url(#{HATCHES[(i + 2) % len(HATCHES)][0]})" stroke="{INK}" stroke-width="0.6"/>',
                t(bx + 22, ry, lang["name"], 13, INK), t(bx + bw, ry, f'{lang["percent"]:.1f}%', 13, SEPIA, MONO, 400, "end"),
                f'<path d="M{bx},{ry + 8} H{bx + bw}" stroke="{SEPIA}" stroke-width="0.4" opacity="0.6"/>']
    return "".join(out)


LATIN = {"name": "Nomen", "location": "Patria", "status": "Gradus", "degree": "Disciplina", "interests": "Studia", "age": "Aetas"}


def persona(x, y, w, h, rows: list) -> str:
    """Written like a Roman roll of names: a Latin label with its English gloss, then the value."""
    out = [frame(x, y, w, h, "Persona", "Who keeps this codex")]
    ly = y + 112
    for key, value in rows:
        out += [caps(x + 24, ly, LATIN.get(key, key), 9, CHALK), italic(x + 24, ly + 13, key, 10)]
        if isinstance(value, list):
            for i, item in enumerate(value):
                out += [t(x + 140, ly + i * 22, NUMERALS[i] + ".", 12, CHALK, SERIF, 600, "end"), t(x + 150, ly + i * 22, shorten(item, 26), 15, INK)]
            ly += 22 * len(value) + 14
        else:
            out.append(t(x + 130, ly, shorten(str(value), 24), 16, INK))
            ly += 38
    return "".join(out)


# --------------------------------------------------------------------------
# The Flight
# --------------------------------------------------------------------------
FEATHER = "M0,0 C4,-10 10,-22 9,-34 C5,-24 -1,-12 0,0 Z M1,-4 L7,-28"


def flight(y: float, days: list[int], start: dt.date, codex: dict) -> tuple[str, int]:
    h = 620
    parts = [t(MARGIN, y + 46, "The Flight", 30, INK, SERIF, 600)]
    parts += [italic(MARGIN, y + 76 + 20 * k, line) for k, line in enumerate(codex["flight_subtitle"])]
    parts.append(inked("icarusmask", 440, 438, W - MARGIN - 330, y + 10, 330 / 440))
    for fx, delay, dur in ((W - 250, 0, 9), (W - 330, 3, 11), (W - 190, 6, 10)):
        parts.append(f'<path d="{FEATHER}" fill="{SEPIA}" stroke="{INK}" stroke-width="0.6" opacity="0">'
                     f'<animateTransform attributeName="transform" type="translate" values="{fx},{y + 250}; {fx - 40},{y + 430}" dur="{dur}s" begin="{delay}s" repeatCount="indefinite"/>'
                     f'<animate attributeName="opacity" values="0;0.8;0.8;0" keyTimes="0;0.15;0.75;1" dur="{dur}s" begin="{delay}s" repeatCount="indefinite"/></path>')
    x0, x1, base, top = MARGIN, W - MARGIN, y + h - 70, y + 380
    step = (x1 - x0) / max(len(days), 1)
    peak_i = max(range(len(days)), key=lambda i: days[i]) if days else 0
    peak = max(days) if days else 0
    parts.append(f'<path d="M{x0},{base + 1} H{x1}" stroke="{INK}" stroke-width="1.2"/>')
    for i, c in enumerate(days):
        bx = x0 + i * step + step * 0.18
        if c:
            bh = 6 + (base - top) * c / peak
            is_peak = i == peak_i
            parts.append(f'<rect x="{bx:.1f}" y="{base - bh:.1f}" width="{step * 0.64:.1f}" height="{bh:.1f}" fill="url(#{"hatchchalk" if is_peak else "hatch1"})" '
                         f'stroke="{CHALK if is_peak else INK}" stroke-width="{1.2 if is_peak else 0.8}"/>')
        else:
            parts.append(f'<circle cx="{bx + step * 0.32:.1f}" cy="{base - 3}" r="1.2" fill="{SEPIA}" opacity="0.6"/>')
    parts += [caps(x0, base + 26, f"{start:%d %b}", 9), caps(x1, base + 26, "today", 9, SEPIA, "end"),
              italic(x0, base + 54, f"{sum(days):,} works in sixty days")]
    if peak:
        sx = x0 + peak_i * step + step / 2
        sy = base - (6 + (base - top)) - 46
        rays = "".join(f'<path d="M0,-17 L0,-27" transform="rotate({a})"/>' for a in range(0, 360, 30))
        parts.append(f'<g transform="translate({sx:.1f},{sy:.1f})"><circle r="12" fill="{GOLD}" stroke="{INK}" stroke-width="1"/>'
                     f'<g stroke="{GOLD}" stroke-width="2" stroke-linecap="round">{rays}'
                     f'<animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="40s" repeatCount="indefinite"/></g></g>')
        peak_day = start + dt.timedelta(days=peak_i)
        left = sx < W / 2
        parts.append(caps(sx + (36 if left else -36), sy + 4, f"zenith · {peak_day:%d %b} · {peak} works", 9, CHALK, "start" if left else "end"))
    return "".join(parts), h


# --------------------------------------------------------------------------
# Dispatches, Oracle, Laurels, Workshop
# --------------------------------------------------------------------------
def dispatches(y: float, events: list[dict]) -> tuple[str, int]:
    h = 250
    out = [frame(MARGIN, y, W - 2 * MARGIN, h, "Dispatches", "Messages carried by Hermes"),
           f'<path d="M150,{y + 100} V{y + h - 22}" stroke="{CHALK}" stroke-width="0.8" opacity="0.7"/>']
    if not events:
        out.append(italic(W / 2, y + 160, "No dispatches lately. Hermes rests.", 15, SEPIA, "middle"))
    for i, e in enumerate(events[:5]):
        ry = y + 124 + i * 26
        out += [t(84, ry, e["time"], 12, SEPIA, MONO), t(166, ry, shorten(e["repo"], 40), 14, INK),
                italic(W - 84, ry, e["status"], 13, CHALK, "end"),
                f'<path d="M84,{ry + 9} H{W - 84}" stroke="{SEPIA}" stroke-width="0.4" opacity="0.5"/>']
    return "".join(out), h


def oracle(y: float, whispers: list[str]) -> tuple[str, int]:
    h = 340
    out = [frame(MARGIN, y, W - 2 * MARGIN, h, "Whispers of the Oracle", "Dreams sent at night, as Oneiros came to Agamemnon"),
           inked("nestormask", 240, 327, 84, y + 100, 220 / 327),
           f'<image href="{data_uri("krater.png", "image/png")}" x="{W - 84 - 210}" y="{y + 100}" width="210" height="215"/>']
    n = len(whispers)
    for i, line in enumerate(whispers):
        lines = wrap("“" + line + "”", 30)
        body = "".join(italic(W / 2 - 20, y + 196 + k * 28 - (len(lines) - 1) * 14, ln, 19, INK, "middle") for k, ln in enumerate(lines))
        out.append(f'<g opacity="{1 if i == 0 else 0}">{timed_opacity(i, n, 6) if n > 1 else ""}{body}</g>')
    out.append(caps(W / 2 - 20, y + 290, "the oracle speaks", 8.5, SEPIA, "middle"))
    return "".join(out), h


LAUREL_ICONS = {
    "column": "M6 4h12 M7 4l1 3h8l1-3 M9 7v12 M12 7v12 M15 7v12 M7 19h10 M5 22h14",
    "wing": "M3 15c4-1 8-4 10-9 1 4 0 8-2 10 3 0 6-1 9-3-2 4-6 6-10 6-3 0-5-1-7-4z",
    "hammer": "M14 4l6 6-3 3-6-6z M11 7l-8 8 3 3 8-8 M4 21h8",
    "owl": "M6 6l2 2 M18 6l-2 2 M5 11a7 7 0 0 0 14 0c0-3-3-5-7-5s-7 2-7 5z M9 11h.01 M15 11h.01 M12 13l-1 2h2z M8 19l-1 3 M16 19l1 3",
    "club": "M14 3c3 0 5 3 4 6l-6 12-3-1 3-12c-1-3 0-5 2-5z",
    "moon": "M20 14a8 8 0 1 1-10-10 7 7 0 0 0 10 10z",
}


def laurel(cx, cy, r) -> str:
    out = []
    for side in (-1, 1):
        for k in range(7):
            a = math.radians(90 + side * (28 + k * 20))
            lx, ly = cx + r * math.cos(a), cy + r * math.sin(a)
            rot = math.degrees(a) + (90 if side > 0 else -90) + side * 25
            out.append(f'<ellipse cx="{lx:.1f}" cy="{ly:.1f}" rx="2.6" ry="6" fill="{GOLD}" stroke="{INK}" stroke-width="0.5" transform="rotate({rot:.0f},{lx:.1f},{ly:.1f})"/>')
    return "".join(out)


def laurels(y: float, items: list[dict]) -> tuple[str, int]:
    rows = math.ceil(len(items) / 3)
    h = 116 + rows * 90
    out = [frame(MARGIN, y, W - 2 * MARGIN, h, "Laurels", "Honours won in the arena")]
    gap = 14
    tw = (W - 2 * MARGIN - 48 - gap * 2) / 3
    for i, it in enumerate(items):
        tx, ty = MARGIN + 24 + (i % 3) * (tw + gap), y + 104 + (i // 3) * 90
        out += [laurel(tx + 34, ty + 34, 26),
                f'<path d="{LAUREL_ICONS.get(it["icon"], LAUREL_ICONS["column"])}" fill="none" stroke="{INK}" stroke-width="1.5" stroke-linecap="round" '
                f'stroke-linejoin="round" transform="translate({tx + 25},{ty + 25}) scale(0.75)"/>',
                t(tx + 74, ty + 30, it["name"], 15, INK, SERIF, 600), caps(tx + 74, ty + 48, it["tech"], 8)]
    return "".join(out), h


def workshop(y: float, categories: list[dict]) -> tuple[str, int]:
    """Each tool on a round shield; categories are rows, and shields wrap onto new lines."""
    out, ry = [], y + 104
    left, right = MARGIN + 24, W - MARGIN - 24
    for cat in categories:
        out.append(caps(left, ry + 6, cat["category"], 9, CHALK))
        cx, line_y = left, ry + 22
        for item in cat["items"]:
            cw = 58 + item.get("text_width", len(item["label"]) * 9.5) * 0.72
            if cx + cw > right and cx > left:
                cx, line_y = left, line_y + 46
            out.append(f'<circle cx="{cx + 17}" cy="{line_y + 16}" r="16" fill="{PARCH}" stroke="{INK}" stroke-width="1.1"/>'
                       f'<circle cx="{cx + 17}" cy="{line_y + 16}" r="12.5" fill="none" stroke="{SEPIA}" stroke-width="0.5"/>')
            if item.get("icon"):
                out.append(f'<path d="{item["icon"]}" fill="{INK}" transform="translate({cx + 10},{line_y + 9}) scale({14 / 24:.4f})"/>')
            else:
                out.append(f'<circle cx="{cx + 17}" cy="{line_y + 16}" r="3" fill="{INK}"/>')
            out.append(t(cx + 40, line_y + 21, item["label"], 13, INK))
            cx += cw
        ry = line_y + 58
    h = ry - y + 6
    return frame(MARGIN, y, W - 2 * MARGIN, h, "The Workshop", "Tools on the bench") + "".join(out), h


# --------------------------------------------------------------------------
# The Ouroboros
# --------------------------------------------------------------------------
def ouroboros(y: float, year: list[int], first_day: dt.date) -> tuple[str, int]:
    """Each day of the past year is an ink stroke around a ring (oldest at the top,
    clockwise to today), with the serpent swallowing its tail inside it."""
    h = 720
    cx, cy, r_tick, r_snake = W / 2, y + 400, 196, 150
    peak = max(year) if year and max(year) else 1
    parts = [t(MARGIN, y + 46, "The Ouroboros", 30, INK, SERIF, 600), italic(MARGIN, y + 76, "A year of work, swallowing its own tail.")]
    n = len(year)
    for i, c in enumerate(year):
        deg = -90 + i / n * 360
        if c:
            x0, y0 = polar(cx, cy, r_tick, deg)
            x1, y1 = polar(cx, cy, r_tick + 8 + 46 * min(1, c / peak), deg)
            parts.append(f'<path d="M{x0:.1f},{y0:.1f} L{x1:.1f},{y1:.1f}" stroke="{INK}" stroke-width="1.6" stroke-linecap="round" opacity="{0.35 + 0.65 * min(1, c / peak):.2f}"/>')
        else:
            x0, y0 = polar(cx, cy, r_tick + 2, deg)
            parts.append(f'<circle cx="{x0:.1f}" cy="{y0:.1f}" r="0.9" fill="{SEPIA}" opacity="0.45"/>')
    for i in range(n):
        day = first_day + dt.timedelta(days=i)
        if day.day == 1:
            deg = -90 + i / n * 360
            lx, ly = polar(cx, cy, r_tick + 70, deg)
            tx, ty = polar(cx, cy, r_tick - 8, deg)
            ox, oy = polar(cx, cy, r_tick - 2, deg)
            parts += [f'<path d="M{tx:.1f},{ty:.1f} L{ox:.1f},{oy:.1f}" stroke="{CHALK}" stroke-width="1.2"/>',
                      t(lx, ly + 4, NUMERALS[day.month - 1], 12, SEPIA, SERIF, 600, "middle")]
    parts += [f'<path d="{arc(cx, cy, r_snake, -84, 190)}" fill="none" stroke="{INK}" stroke-width="15" stroke-linecap="round"/>',
              f'<path d="{arc(cx, cy, r_snake, 186, 222)}" fill="none" stroke="{INK}" stroke-width="10" stroke-linecap="round"/>',
              f'<path d="{arc(cx, cy, r_snake, 218, 248)}" fill="none" stroke="{INK}" stroke-width="5" stroke-linecap="round"/>',
              # scales: a dashed parchment line that slowly flows along the body, so the serpent seems to move
              f'<path d="{arc(cx, cy, r_snake, -80, 214)}" fill="none" stroke="{PARCH}" stroke-width="5" stroke-dasharray="3 7" opacity="0.55">'
              f'<animate attributeName="stroke-dashoffset" values="0;-20" dur="1.6s" repeatCount="indefinite"/></path>',
              f'<path d="{arc(cx, cy, r_snake + 9, -80, 200)}" fill="none" stroke="{SEPIA}" stroke-width="0.7" opacity="0.6"/>']
    hx, hy = polar(cx, cy, r_snake, -90)
    parts.append(f'<g transform="translate({hx:.1f},{hy:.1f})">'
                 f'<path d="M10,-9 C-6,-14 -24,-12 -36,-5 L-48,-9 L-40,-1 L-48,6 L-36,3 C-24,10 -6,12 10,8 Z" fill="{INK}"/>'
                 f'<circle cx="-20" cy="-5" r="2.4" fill="{PARCH}"/><circle cx="-20" cy="-5" r="1" fill="{CHALK}"/></g>')
    total = sum(year)
    parts += [t(cx, cy - 8, f"{total:,}", 46, INK, SERIF, 600, "middle"), caps(cx, cy + 18, "works in one turn of the sun", 9, SEPIA, "middle")]
    if total:
        best = max(range(n), key=lambda i: year[i])
        parts.append(italic(cx, cy + 50, f"Fullest day: {first_day + dt.timedelta(days=best):%d %b} · {year[best]}", 13, SEPIA, "middle"))
    return "".join(parts), h


# --------------------------------------------------------------------------
# Document
# --------------------------------------------------------------------------
def defs(hands_h: int) -> str:
    hatch = "".join(f'<pattern id="{pid}" width="{g}" height="{g}" patternUnits="userSpaceOnUse" patternTransform="rotate({rot})">'
                    f'<rect width="{g}" height="{g}" fill="{PARCH}"/><path d="M0,0 V{g}" stroke="{INK}" stroke-width="1.2"/></pattern>'
                    for pid, rot, g in HATCHES)
    masks = "".join(f'<mask id="{mid}" maskUnits="userSpaceOnUse"><image href="{data_uri(name, "image/png")}" width="{w}" height="{h}"/></mask>'
                    for mid, name, w, h in (("vitmask", "vitruvian.png", 480, 600), ("icarusmask", "icarus.png", 440, 438),
                                            ("nestormask", "nestor.png", 240, 327), ("flyermask", "flying-machine.png", 330, 288),
                                            ("drillmask", "drill.png", 130, 172)))
    return f'''<defs>
    <style>@font-face {{ font-family: Cinzel; font-weight: 600; src: url({data_uri("cinzel-600.woff2", "font/woff2")}) format("woff2"); }}
      @font-face {{ font-family: Cardo; src: url({data_uri("cardo-greek.woff2", "font/woff2")}) format("woff2"); unicode-range: U+0370-03FF; }}
      @font-face {{ font-family: Cardo; src: url({data_uri("cardo-greek-ext.woff2", "font/woff2")}) format("woff2"); unicode-range: U+1F00-1FFF; }}</style>
    <filter id="paper" x="0" y="0" width="100%" height="100%">
      <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="7"/>
      <feColorMatrix type="matrix" values="0 0 0 0 0.48  0 0 0 0 0.36  0 0 0 0 0.2  0 0 0 0.07 0"/>
    </filter>
    <radialGradient id="vignette" cx="0.5" cy="0.5" r="0.75"><stop offset="0.6" stop-color="{SEPIA}" stop-opacity="0"/><stop offset="1" stop-color="{SEPIA}" stop-opacity="0.22"/></radialGradient>
    <linearGradient id="fadeY" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#000"/><stop offset="0.08" stop-color="#fff"/><stop offset="0.85" stop-color="#fff"/><stop offset="1" stop-color="#000"/></linearGradient>
    <mask id="handsfade"><rect width="{W}" height="{hands_h}" fill="url(#fadeY)"/></mask>
    <mask id="rwmask" maskUnits="userSpaceOnUse"><image href="{data_uri("rw-mark.png", "image/png")}" width="144" height="88"/></mask>
    {masks}
    {hatch}
    <pattern id="hatchchalk" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="4" height="4" fill="{PARCH}"/><path d="M0,0 V4" stroke="{CHALK}" stroke-width="2.2"/></pattern>
  </defs>'''


def build(content: dict, stats: dict, streaks: dict, grade: str, percentile: float,
          year: list[int], events: list[dict], synced: str, today: dt.date, **_unused) -> str:
    """The whole codex page. `year` is contributions per day for the last 365 days, oldest first."""
    codex = content["codex"]
    first_day = today - dt.timedelta(days=len(year) - 1)
    year_total = sum(year)
    sections = []
    head, y = header(content)
    sections.append(head)

    def add(result):
        nonlocal y
        part, height = result
        sections.append(part)
        y += height + GAP

    add(motto(y, codex["motto"]))
    add(offerings(y, stats, streaks, grade))
    add(proportions(y, content))
    add(astrolabes(y, streaks, percentile, year_total))
    row_h = 380
    sections += [tongues(MARGIN, y, HALF, row_h, stats["languages"]), persona(MARGIN + HALF + GAP, y, HALF, row_h, content["driver_profile"])]
    y += row_h + GAP
    add(flight(y, year[-60:], today - dt.timedelta(days=59), codex))
    add(dispatches(y, events))
    add(oracle(y, codex["whispers"]))
    add(laurels(y, codex["laurels"]))
    add(workshop(y, content["tech_stack"]))
    add(ouroboros(y, year, first_day))
    sections.append(caps(W / 2, y + 10, f"Copied by the scribe on {synced} · renewed every twelve hours", 8.5, SEPIA, "middle"))
    height = round(y + 40)
    summary = (f'{content["profile"]["full_name"]}: the Engineer\'s Codex. {stats["commits"]} commits, {stats["stars"]} stars, '
               f'{stats["prs"]} pull requests, {streaks["total"]} contributions, current streak {streaks["current"]["length"]} days, '
               f'grade {grade}. Languages: ' + ", ".join(f'{lang["name"]} {lang["percent"]:.0f}%' for lang in stats["languages"][:3]) + ". "
               + "Tools: " + "; ".join(f'{c["category"]}: {", ".join(i["label"] for i in c["items"])}' for c in content["tech_stack"]) + ".")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" viewBox="0 0 {W} {height}" role="img" aria-label="{esc(summary)}">\n'
            f'  <title>{esc(summary)}</title>\n  {defs(309)}\n'
            f'  <rect width="{W}" height="{height}" fill="{PARCH}"/>\n  <rect width="{W}" height="{height}" filter="url(#paper)"/>\n'
            + "\n".join(sections)
            + f'\n  <rect width="{W}" height="{height}" fill="url(#vignette)"/>\n</svg>\n')
