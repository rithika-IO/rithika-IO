"""Mission-control dashboard drawing for the profile README.

Presentation only: every function here takes plain data (dicts, lists, numbers)
and returns SVG text. Fetching data from GitHub lives in build_panels.py, so the
look can change without touching the data code (separation of concerns).

Layout is built from a few reusable components (panel, label, pill, gauge,
hotspot) so every section shares one visual language. build() is the entry
point: it stacks the top dashboard and the lower sections into one SVG.
"""
from __future__ import annotations

import base64
import math
import os
import random
import re
from pathlib import Path

# --------------------------------------------------------------------------
# Design tokens
# --------------------------------------------------------------------------
BG, INK = "#1A1A1D", "#0B0B0C"
FG, MUTED = "#ECE7E0", "#A8A39B"
PINK, CORAL = "#E8476A", "#F06A4E"
TEAL, YELLOW, ORANGE, GREEN = "#5EC8BE", "#F5C842", "#F08A3C", "#8EDB5A"
LINE = "#ECE7E014"                                  # hairline borders: cream at ~8%
PANEL_BG = "#121214"
SANS = "'Inter','Segoe UI','Helvetica Neue',Helvetica,Arial,sans-serif"
MONO = "'JetBrains Mono','SFMono-Regular',Menlo,Consolas,monospace"
W = 900                                     # close to GitHub's README width, so text shows near real size
HALF = (W - 40 - 14) / 2                    # width of a panel when two share a row
GAP = 14

# Top-down car photo (nose up). Positions below are in the photo's own units
# (the 1200 x 2800 crop of the original), so hotspots stay glued to the tyres
# whatever size the photo is drawn at.
CAR_PHOTO = Path(os.environ.get("CAR_PHOTO", Path(__file__).resolve().parent.parent / "assets" / "car-top.jpg"))
PHOTO_W, PHOTO_H = 1200, 2800
# The RW monogram, cut out of the brand tile as white lettering on transparency.
# It is used as a mask, so the letters can take any palette colour.
BRAND_MARK = CAR_PHOTO.with_name("rw-mark.png")
MARK_W, MARK_H = 144, 88
PHOTO_SPOTS = {"front_left": (244, 637), "front_right": (947, 637), "cockpit": (590, 1204),
               "rear_left": (250, 2170), "rear_right": (942, 2170)}


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------
def esc(value) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;")


def text(x, y, content, size=14, fill=FG, weight=400, anchor="start", family=SANS, extra="") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" font-family="{family}" font-weight="{weight}" '
            f'font-size="{size}" fill="{fill}" {extra}>{esc(content)}</text>')


def label(x, y, content, fill=MUTED, size=10.5, anchor="start") -> str:
    """Small uppercase monospace label, like ICE POWER or LAP on the dashboard."""
    return text(x, y, str(content).upper(), size, fill, 500, anchor, MONO, 'letter-spacing="1.2"')


def panel(x, y, w, h, title: str | None = None, subtitle: str | None = None) -> str:
    out = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="{PANEL_BG}" stroke="{LINE}" stroke-width="1"/>'
    if title:
        out += text(x + 20, y + 34, title, 18, FG, 500)
    if subtitle:
        out += label(x + 20, y + 54, subtitle)
    return out


def pill(x, y, content, colour=TEAL, anchor="start") -> str:
    """Small rounded tag with tinted background, e.g. the "60D" badge."""
    w = len(content) * 6.6 + 20
    x0 = x - w if anchor == "end" else x
    return (f'<rect x="{x0:.1f}" y="{y}" width="{w:.1f}" height="20" rx="10" fill="{colour}" fill-opacity="0.14"/>'
            + text(x0 + w / 2, y + 14, content.upper(), 9.5, colour, 600, "middle", MONO, 'letter-spacing="1"'))


def live_dot(cx, cy, colour=PINK, r=3.5) -> str:
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{colour}"><animate attributeName="opacity" values="1;0.25;1" dur="1.4s" repeatCount="indefinite"/></circle>')


def hotspot(cx, cy) -> str:
    """White dot with an expanding ring, marking a point on the car."""
    return (f'<circle cx="{cx}" cy="{cy}" r="9" fill="none" stroke="{FG}" stroke-width="1.5" opacity="0">'
            f'<animate attributeName="r" values="9;24" dur="2.2s" repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" values="0.7;0" dur="2.2s" repeatCount="indefinite"/></circle>'
            f'<circle cx="{cx}" cy="{cy}" r="10" fill="{FG}" opacity="0.18"/>'
            f'<circle cx="{cx}" cy="{cy}" r="6.5" fill="{FG}"/>')


def arc_path(cx, cy, r, a0, a1) -> str:
    """Circular arc from angle a0 to a1 (degrees, 0 = up, clockwise)."""
    p = lambda a: (cx + r * math.sin(math.radians(a)), cy - r * math.cos(math.radians(a)))
    (x0, y0), (x1, y1) = p(a0), p(a1)
    large = 1 if (a1 - a0) % 360 > 180 else 0
    return f"M{x0:.1f},{y0:.1f} A{r},{r} 0 {large} 1 {x1:.1f},{y1:.1f}"


def gauge(cx, cy, r, fraction, value, unit, lo, hi, colour=PINK) -> str:
    """Segmented arc gauge like the RPM dial: dim track, glowing filled segments, value in the middle."""
    start, sweep, segs = -125, 250, 22
    out = []
    for i in range(segs):
        a0 = start + i * sweep / segs + 1.2
        a1 = start + (i + 1) * sweep / segs - 1.2
        on = (i + 0.5) / segs <= fraction
        tint = colour if on else FG
        op = 0.35 + 0.65 * (i / segs) if on else 0.07
        out.append(f'<path d="{arc_path(cx, cy, r, a0, a1)}" fill="none" stroke="{tint}" stroke-width="{r * 0.26:.1f}" opacity="{op:.2f}"/>')
    out.append(f'<path d="{arc_path(cx, cy, r - r * 0.3, start, start + sweep * max(fraction, 0.01))}" fill="none" stroke="{colour}" stroke-width="1.5" opacity="0.6"/>')
    out.append(label(cx, cy - r * 0.2, unit, MUTED, 9, "middle"))
    out.append(text(cx, cy + r * 0.38, value, round(r * 0.5), FG, 600, "middle"))
    out.append(label(cx - r * 0.72, cy + r + 12, lo, MUTED, 9, "middle"))
    out.append(label(cx + r * 0.72, cy + r + 12, hi, MUTED, 9, "middle"))
    return "".join(out)


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------
ACCENTS = [PINK, TEAL, ORANGE, YELLOW, GREEN, CORAL]      # cycled for languages and badges


def brand_tile(x, y, size) -> str:
    """The RW monogram on a dark rounded tile, with a pink speed stripe underneath."""
    mw = size * 0.78
    mh = mw * MARK_H / MARK_W
    mx, my = x + (size - mw) / 2, y + (size - mh) / 2 - 3
    return (f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="{size * 0.24:.1f}" fill="{INK}" stroke="{PINK}" stroke-opacity="0.55" stroke-width="1.5"/>'
            f'<rect x="0" y="0" width="{MARK_W}" height="{MARK_H}" fill="{FG}" mask="url(#rwmask)" '
            f'transform="translate({mx:.1f},{my:.1f}) scale({mw / MARK_W:.4f})"/>'
            f'<path d="M{x + size * 0.30:.1f},{y + size * 0.84:.1f} H{x + size * 0.78:.1f} l-4,4 H{x + size * 0.26:.1f} Z" fill="{PINK}"/>')


def header(profile: dict, stats: dict, streaks: dict, grade: str) -> tuple[str, int]:
    """Row 1: logo and driver chip. Row 2: six stat tiles across the full width."""
    h = 160
    parts = [
        f'<rect x="0" y="0" width="{W}" height="{h}" fill="{BG}"/>',
        brand_tile(20, 14, 56),
        text(92, 48, "Mission Control", 20, FG, 600),
        live_dot(262, 42),
    ]
    cx = W - 240
    parts += [
        f'<rect x="{cx}" y="16" width="220" height="52" rx="26" fill="{PANEL_BG}" stroke="{LINE}"/>',
        f'<circle cx="{cx + 26}" cy="42" r="19" fill="{PINK}"/>',
        text(cx + 26, 48, profile["race_number"], 16, INK, 800, "middle", extra='font-style="italic"'),
        label(cx + 54, 36, "DRIVER"),
        text(cx + 54, 57, profile["full_name"], 15, FG, 500),
    ]
    tiles = [("COMMITS", f'{stats["commits"]:,}', "", TEAL), ("STARS", f'{stats["stars"]}', "", YELLOW),
             ("PULL REQS", f'{stats["prs"]}', "", ORANGE), ("STREAK", f'{streaks["current"]["length"]}', f'/{streaks["longest"]["length"]}', GREEN),
             ("GRADE", grade, "", PINK), ("CONTRIBS", f'{streaks["total"]:,}', "", CORAL)]
    gap = 10
    tw = (W - 40 - gap * (len(tiles) - 1)) / len(tiles)
    for i, (key, value, suffix, colour) in enumerate(tiles):
        tx = 20 + i * (tw + gap)
        parts += [f'<rect x="{tx:.1f}" y="88" width="{tw:.1f}" height="60" rx="12" fill="{PANEL_BG}" stroke="{LINE}"/>',
                  f'<rect x="{tx + 14:.1f}" y="100" width="14" height="3" rx="1.5" fill="{colour}"/>',
                  label(tx + 14, 118, key), text(tx + 14, 140, value, 19, FG, 600)]
        if suffix:
            parts.append(text(tx + 16 + len(value) * 11.5, 140, suffix, 13, MUTED))
    return "".join(parts), h


QUOTE_STEP = 7.0                                                 # seconds per quote: longer lines need reading time


def quote_band(x, y, w, quotes: list[dict]) -> tuple[str, int]:
    """Pit-wall style banner that rotates through driver quotes (two lines at most each)."""
    h, n = 150, len(quotes)
    parts = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="{PANEL_BG}" stroke="{LINE}"/>',
             f'<rect x="{x}" y="{y + 22}" width="4" height="{h - 44}" rx="2" fill="{PINK}"/>',
             text(x + 28, y + 78, "“", 60, PINK, 700, extra='opacity="0.9"')]
    for i, q in enumerate(quotes):
        lines = wrap(q["text"], int((w - 100) / 12))[:2]
        top = y + 62 + (2 - len(lines)) * 16                     # one-line quotes sit in the middle of the band
        body = "".join(text(x + 64, top + k * 32, line, 23, FG, 500, extra='font-style="italic"') for k, line in enumerate(lines))
        body += label(x + 64, top + len(lines) * 32, f'{q["author"]} · {q["note"]}', MUTED, 10)
        parts.append(f'<g opacity="{1 if i == 0 else 0}">{timed_opacity(i, n, step=QUOTE_STEP) if n > 1 else ""}{body}</g>')
    return "".join(parts), h


def car_photo(x, y, scale, rotate=False) -> str:
    """Place the shared photo. rotate=True turns it 90 degrees clockwise (nose to the right)."""
    if rotate:
        return f'<use href="#carphoto" transform="translate({x + PHOTO_H * scale:.1f},{y:.1f}) rotate(90) scale({scale:.4f})"/>'
    return f'<use href="#carphoto" transform="translate({x:.1f},{y:.1f}) scale({scale:.4f})"/>'


CYCLE_STEP = 4.0                                                 # seconds each callout stays on screen
CALLOUT_ACCENTS = [TEAL, PINK, YELLOW, GREEN]                    # the four skill cards, in order
KIND_ACCENTS = {"Full-stack": PINK, "Enterprise app": ORANGE, "Machine learning": GREEN, "CLI tool": YELLOW,
                "Language tooling": CORAL, "Backend service": TEAL, "Frontend": PINK}


def callout_sequence(skills: list[dict], repos: list[dict]) -> list[dict]:
    """One lap per repo: the card circles the four tyres, then stops at the cockpit for the next repo.

    Lap 1: Backend, Frontend, APIs, Infra, repo 1. Lap 2: ... repo 2, and so on
    until every repo has had its turn, then the whole loop starts again.
    """
    skills = [dict(c, accent=CALLOUT_ACCENTS[i % len(CALLOUT_ACCENTS)]) for i, c in enumerate(skills)]
    repos = [dict(c, accent=KIND_ACCENTS.get(c.get("kind"), MUTED)) for c in repos]
    if not repos or not skills:
        return skills or repos
    return [card for repo in repos for card in (*skills, repo)]


def timed_opacity(i: int, n: int, fade_s: float = 0.4, step: float = CYCLE_STEP) -> str:
    """SMIL opacity track: visible only during slot i of n, so the slots take turns in one shared loop.

    keyTimes are fractions of the whole loop, so the fade is converted from
    seconds; that keeps it 0.4 s whether the loop has 5 slots or 30.
    """
    a, b = i / n, (i + 1) / n
    fade = fade_s / (n * step)
    if i == 0:
        times, values = [0, b - fade, b, 1], [1, 1, 0, 0]
    else:
        times, values = [0, a, a + fade / 2, b - fade, b, 1], [0, 0, 1, 1, 0, 0]
    return (f'<animate attributeName="opacity" dur="{n * step}s" repeatCount="indefinite" '
            f'keyTimes="{";".join(f"{t:.4f}" for t in times)}" values="{";".join(map(str, values))}"/>')


def car_section(x, y, w, h, callouts: list[dict]) -> str:
    """Photo plus one callout card that travels between the markers on a loop (like a telemetry readout)."""
    s = (h - 16) / PHOTO_H                                       # fit the photo to the column height
    left, top = x + w * 0.6 - PHOTO_W * s / 2, y + 8
    to_screen = lambda px, py: (left + px * s, top + py * s)     # photo units -> screen
    # black panel: the photo's road surface was regraded to the same near-black, so the car blends in
    parts = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="{INK}" stroke="{LINE}"/>', car_photo(left, top, s)]
    parts += [hotspot(*to_screen(*xy)) for xy in PHOTO_SPOTS.values()]

    n = len(callouts)
    card_x, card_w, card_h = x + 24, 236, 220
    card_ys = []
    for i, c in enumerate(callouts):
        sx, sy = to_screen(*PHOTO_SPOTS[c["spot"]])
        cy = min(max(sy - card_h / 2, y + 18), y + h - card_h - 18)   # keep the card inside the column
        card_ys.append(cy)
        colour = c["accent"]
        # leader line + highlight ring for this marker, shown only during its slot
        parts.append(f'<g opacity="{1 if i == 0 else 0}">{timed_opacity(i, n)}'
                     f'<path d="M{card_x + card_w + 4},{sy:.0f} H{sx - 14:.0f}" fill="none" stroke="{colour}" stroke-width="1.2" stroke-dasharray="3 4" opacity="0.8"/>'
                     f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="13" fill="none" stroke="{colour}" stroke-width="2"/></g>')

    # the card frame slides between positions; each topic's text fades in during its own slot
    keys, vals = [], []
    for i in range(n):
        keys += [i / n, (i + 1) / n - 0.5 / (n * CYCLE_STEP)]   # hold, then a 0.5 s slide to the next marker
        vals += [card_ys[i], card_ys[i]]
    keys.append(1.0); vals.append(card_ys[0])
    slide = (f'<animateTransform attributeName="transform" type="translate" dur="{n * CYCLE_STEP}s" repeatCount="indefinite" '
             f'keyTimes="{";".join(f"{k:.4f}" for k in keys)}" values="{";".join(f"0,{v - card_ys[0]:.1f}" for v in vals)}"/>')
    cy = card_ys[0]
    card = [f'<rect x="{card_x}" y="{cy:.1f}" width="{card_w}" height="{card_h}" rx="16" fill="#141416" fill-opacity="0.94" stroke="{LINE}"/>']
    for i, c in enumerate(callouts):
        colour = c["accent"]
        body = [f'<rect x="{card_x + 18}" y="{cy + 18:.1f}" width="22" height="3" rx="1.5" fill="{colour}"/>',
                text(card_x + 18, cy + 46, c["title"] if len(c["title"]) <= 20 else c["title"][:19] + "…", 18, FG, 500)]
        for r, (value, name) in enumerate(c["rows"]):
            ry = cy + 86 + r * 46
            value = value if len(value) <= 24 else value[:23] + "…"      # long repo names must fit the card
            body += [text(card_x + 18, ry, value, 22 if r == 0 and len(value) < 10 else 15, colour if r == 0 else FG, 600), label(card_x + 18, ry + 17, name)]
        card.append(f'<g opacity="{1 if i == 0 else 0}">{timed_opacity(i, n)}{"".join(body)}</g>')
    parts.append(f'<g>{slide}{"".join(card)}</g>')
    return "".join(parts)


def powertrain(x, y, w, h, languages: list[dict]) -> str:
    parts = [panel(x, y, w, h, "Powertrain", f"{len(languages)} languages combined")]
    box_w = (w - 52) / 2
    for i, lang in enumerate(languages[:2]):
        bx = x + 20 + i * (box_w + 12)
        colour = ACCENTS[i]
        pct = f'{lang["percent"]:.0f}'
        parts += [f'<rect x="{bx:.0f}" y="{y + 72}" width="{box_w:.0f}" height="64" rx="12" fill="{INK}" stroke="{LINE}"/>',
                  f'<rect x="{bx + 12:.0f}" y="{y + 84}" width="14" height="3" rx="1.5" fill="{colour}"/>',
                  label(bx + 12, y + 102, lang["name"]),
                  text(bx + 12, y + 127, pct, 24, FG, 600), text(bx + 14 + len(pct) * 14.5, y + 127, "%", 12, MUTED)]
    bar_y, bar_w, off = y + 152, w - 40, 0.0
    for i, lang in enumerate(languages):
        seg = bar_w * lang["percent"] / 100
        parts.append(f'<rect x="{x + 20 + off:.1f}" y="{bar_y}" width="{max(seg - 2, 1):.1f}" height="6" rx="3" fill="{ACCENTS[i % len(ACCENTS)]}"/>')
        off += seg
    for i, lang in enumerate(languages[2:7]):
        ry = y + 192 + i * 32
        parts += [f'<rect x="{x + 20}" y="{ry + 11}" width="{w - 40}" height="1" fill="{LINE}"/>',
                  f'<circle cx="{x + 24}" cy="{ry - 4}" r="3.5" fill="{ACCENTS[(i + 2) % len(ACCENTS)]}"/>',
                  label(x + 36, ry, lang["name"]), text(x + w - 20, ry, f'{lang["percent"]:.1f}%', 12.5, FG, 500, "end", MONO)]
    return "".join(parts)


def engine_load(x, y, w, h, daily: list[int]) -> str:
    parts = [panel(x, y, w, h, "Engine load", f"Contributions · last {len(daily)} days")]
    parts.append(pill(x + w - 20, y + 20, f"{len(daily)}D", ORANGE, "end"))
    cx0, cx1, top, bottom = x + 36, x + w - 20, y + 96, y + h - 34
    peak = max(daily) or 1
    for k in range(3):
        gy = bottom - (bottom - top) * k / 2
        parts += [f'<rect x="{cx0}" y="{gy:.0f}" width="{cx1 - cx0}" height="1" fill="{LINE}"/>',
                  label(cx0 - 8, gy + 3, f"{peak * k / 2:.0f}", MUTED, 8.5, "end")]
    step = (cx1 - cx0) / len(daily)
    for i, v in enumerate(daily):
        bh = (bottom - top) * v / peak
        parts.append(f'<rect x="{cx0 + i * step + step * 0.18:.1f}" y="{bottom - bh:.1f}" width="{step * 0.64:.1f}" height="{max(bh, 1):.1f}" rx="1" fill="url(#loadbar)" opacity="{0.5 + 0.5 * v / peak:.2f}"/>')
    best = max(range(len(daily)), key=lambda i: daily[i])
    bx = cx0 + best * step + step / 2
    right = bx < cx1 - 50
    parts += [f'<line x1="{bx:.1f}" y1="{top - 10}" x2="{bx:.1f}" y2="{bottom}" stroke="{FG}" stroke-width="1.5"/>',
              text(bx + (8 if right else -8), top + 4, daily[best], 20, FG, 500, "start" if right else "end")]
    for frac, txt in ((0, f"-{len(daily)}D"), (0.5, f"-{len(daily) // 2}D"), (1, "TODAY")):
        parts.append(label(cx0 + (cx1 - cx0) * frac, bottom + 18, txt, MUTED, 8.5, ["start", "middle", "end"][int(frac * 2)]))
    return "".join(parts)


def gauges(x, y, w, h, streaks: dict, grade: str, percentile: float, year_total: int) -> str:
    parts = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="{PANEL_BG}" stroke="{LINE}"/>']
    top = max(1000, math.ceil(year_total / 500) * 500)           # dial scale grows with the yearly total
    top_label = f"{top / 1000:g}K"
    cells = [(year_total / top, f"{year_total}", "CONTRIB", "0", top_label, PINK),
             (streaks["current"]["length"] / max(streaks["longest"]["length"], 1), f'{streaks["current"]["length"]}D', "STREAK", "0", f'{streaks["longest"]["length"]}', GREEN),
             ((100 - percentile) / 100, grade, "POWER", "C", "S", YELLOW)]
    for i, (frac, val, unit, lo, hi, colour) in enumerate(cells):
        parts.append(gauge(x + w / 6 + i * w / 3, y + h / 2 - 6, min(h * 0.3, w / 8), frac, val, unit, lo, hi, colour))
    return "".join(parts)


def driver_profile(x, y, w, h, rows: list) -> str:
    """An "about me" written as a JSON file, with editor-style syntax colours."""
    parts = [panel(x, y, w, h, "Driver profile"),
             f'<rect x="{x + w - 120}" y="{y + 20}" width="100" height="22" rx="6" fill="{INK}" stroke="{LINE}"/>',
             text(x + w - 70, y + 35, "driver.json", 10.5, MUTED, 500, "middle", MONO)]
    size, step = 13, 22
    char = size * 0.6                                          # monospace glyph width
    lines = []                                                 # each line is a list of (text, colour) pieces

    def value_piece(value):
        if isinstance(value, (int, float)) or str(value).isdigit():
            return (str(value), YELLOW)                        # numbers unquoted, like real JSON
        return (f'"{value}"', FG)

    lines.append([("{", PINK)])
    for i, (key, value) in enumerate(rows):
        comma = [(",", MUTED)] if i < len(rows) - 1 else []
        head = [("  ", FG), (f'"{key}"', TEAL), (": ", MUTED)]
        if isinstance(value, list):
            lines.append(head + [("[", PINK)])
            for j, item in enumerate(value):
                lines.append([("    ", FG), value_piece(item)] + ([(",", MUTED)] if j < len(value) - 1 else []))
            lines.append([("  ", FG), ("]", PINK)] + comma)
        else:
            lines.append(head + [value_piece(value)] + comma)
    lines.append([("}", PINK)])

    ly = y + 78
    for line in lines:
        cx = x + 22
        for piece, colour in line:
            if piece.strip():
                parts.append(text(cx, ly, piece, size, colour, 500 if colour == TEAL else 400, family=MONO, extra='xml:space="preserve"'))
            cx += char * len(piece)
        ly += step
    return "".join(parts)


def system_logs(x, y, w, h, events: list[dict]) -> str:
    parts = [panel(x, y, w, h, "System logs")]
    tx, sx, stx = x + 16, x + 66, x + w - 16
    parts += [f'<rect x="{x + 10}" y="{y + 52}" width="{w - 20}" height="26" rx="8" fill="{INK}"/>',
              label(tx, y + 69, "TIME", MUTED, 9), label(sx, y + 69, "SYSTEM", MUTED, 9), label(stx, y + 69, "STATUS", MUTED, 9, "end")]
    kinds = {"push": TEAL, "pr": YELLOW, "create": GREEN, "issue": CORAL, "star": ORANGE}
    for i, ev in enumerate(events[:5]):
        ry = y + 106 + i * 36
        limit = int((w - 190) / 7.5)
        repo = ev["repo"] if len(ev["repo"]) <= limit else ev["repo"][:limit - 1] + "…"
        parts += [text(tx, ry, ev["time"], 11, FG, 500, family=MONO), text(sx, ry, repo, 12, FG, 500),
                  label(stx, ry, ev["status"], kinds.get(ev["kind"], MUTED), 9, "end")]
    if not events:
        parts.append(label(x + w / 2, y + 130, "NO RECENT ACTIVITY", MUTED, 10, "middle"))
    return "".join(parts)


def build_top(content: dict, stats: dict, streaks: dict, grade: str, percentile: float,
              daily: list[int], year_total: int, events: list[dict]) -> tuple[str, int]:
    """Header, quote, car, then the telemetry panels: one per row, or two side by side."""
    x2 = 20 + HALF + GAP                                       # left edge of a right-hand panel
    head, y = header(content["profile"], stats, streaks, grade)
    body = [head]
    if content.get("quotes"):
        q, qh = quote_band(20, y, W - 40, content["quotes"])
        body.append(q)
        y += qh + GAP
    car_h = 640
    body.append(car_section(20, y, W - 40, car_h, callout_sequence(content["car_callouts"], content.get("repo_cards", []))))
    y += car_h + GAP
    body.append(gauges(20, y, W - 40, 190, streaks, grade, percentile, year_total))
    y += 190 + GAP
    body += [powertrain(20, y, HALF, 360, stats["languages"]), driver_profile(x2, y, HALF, 360, content["driver_profile"])]
    y += 360 + GAP
    body.append(engine_load(20, y, W - 40, 260, daily))
    y += 260 + GAP
    return "\n".join(body), y


# --------------------------------------------------------------------------
# Lower sections: team radio, trophies, garage, track map, footer
# --------------------------------------------------------------------------
PURPLE = "#B57BFF"                                   # F1's "fastest lap" colour, used for that trophy


def readable(colour: str) -> str:
    """Brand colours like SQLite navy vanish on a black chip; lift very dark ones toward cream."""
    r, g, b = (int(colour.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    if lum >= 0.18:
        return colour
    mix = lambda c, f: round(c * 255 * 0.45 + f * 0.55)
    fr, fg, fb = (int(FG.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    return f"#{mix(r, fr):02X}{mix(g, fg):02X}{mix(b, fb):02X}"


def wrap(content: str, width: int) -> list[str]:
    """Greedy word wrap by character count (SVG text has no automatic wrapping)."""
    lines, line = [], ""
    for word in content.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + [line] if line else lines


def team_radio(x, y, w, h, messages: list[str]) -> str:
    """Broadcast-style radio: one message at a time on a shared loop, over an animated voice waveform."""
    n = len(messages)
    parts = [panel(x, y, w, h, "Team radio", "Pit wall to car 33")]
    parts.append(pill(x + w - 20, y + 20, "CH 1", PINK, "end"))
    parts.append(label(x + 20, y + 92, "RACE ENGINEER", PINK, 9.5))
    for i, message in enumerate(messages):
        lines = wrap("“" + message + "”", int((w - 40) / 10.5))
        body = "".join(text(x + 20, y + 124 + k * 28, line, 20, FG, 400, extra='font-style="italic"') for k, line in enumerate(lines))
        parts.append(f'<g opacity="{1 if i == 0 else 0}">{timed_opacity(i, n)}{body}</g>')
    # waveform: each bar breathes at its own pace, which reads as speech
    rng = random.Random(33)
    bars, base, x0 = 64, y + h - 40, x + 20
    step = (w - 40) / bars
    for i in range(bars):
        hs = [rng.uniform(3, 30) for _ in range(4)]
        vals_h = ";".join(f"{v:.1f}" for v in hs + hs[:1])
        vals_y = ";".join(f"{base - v / 2:.1f}" for v in hs + hs[:1])
        colour = PINK if i < bars * 0.62 else "#ECE7E033"
        parts.append(f'<rect x="{x0 + i * step:.1f}" y="{base - hs[0] / 2:.1f}" width="{step * 0.55:.1f}" height="{hs[0]:.1f}" rx="1" fill="{colour}">'
                     f'<animate attributeName="height" values="{vals_h}" dur="{rng.uniform(0.9, 1.6):.2f}s" repeatCount="indefinite"/>'
                     f'<animate attributeName="y" values="{vals_y}" dur="{rng.uniform(0.9, 1.6):.2f}s" repeatCount="indefinite"/></rect>')
    return "".join(parts)


TROPHY_ICONS = {  # 24x24 line icons drawn for this profile
    "trophy": "M7 4h10v4a5 5 0 0 1-10 0z M7 6H4a3 3 0 0 0 3 4 M17 6h3a3 3 0 0 1-3 4 M12 13v4 M8 20h8 M9 17h6",
    "stopwatch": "M12 21a8 8 0 1 0 0-16 8 8 0 0 0 0 16z M12 9v4l3 2 M10 2h4 M12 2v3",
    "headset": "M4 14v-2a8 8 0 0 1 16 0v2 M4 14h3v5H4z M17 14h3v5h-3z M20 19a4 4 0 0 1-4 3h-3",
    "chart": "M4 20h16 M6 16l4-5 3 3 5-7 M18 7h-3 M18 7v3",
    "flag": "M5 21V4 M5 4h13l-2 4 2 4H5",
    "moon": "M20 14a8 8 0 1 1-10-10 7 7 0 0 0 10 10z M17 3l.6 1.4L19 5l-1.4.6L17 7l-.6-1.4L15 5l1.4-.6z",
}
TROPHY_ACCENTS = [YELLOW, PURPLE, TEAL, GREEN, PINK, ORANGE]


def trophies(x, y, w, h, items: list[dict]) -> str:
    parts = [panel(x, y, w, h, "Trophies", f"{len(items)} specialties")]
    cols, gap = (3 if w > 700 else 2), 10
    tw, th = (w - 40 - gap * (cols - 1)) / cols, 56
    for i, t in enumerate(items[:6]):
        tx, ty = x + 20 + (i % cols) * (tw + gap), y + 70 + (i // cols) * (th + gap)
        colour = TROPHY_ACCENTS[i % len(TROPHY_ACCENTS)]
        parts += [f'<rect x="{tx:.1f}" y="{ty}" width="{tw:.1f}" height="{th}" rx="12" fill="{INK}" stroke="{LINE}"/>',
                  f'<circle cx="{tx + 30:.1f}" cy="{ty + th / 2}" r="17" fill="{colour}" fill-opacity="0.14" stroke="{colour}" stroke-opacity="0.5"/>',
                  f'<path d="{TROPHY_ICONS.get(t["icon"], TROPHY_ICONS["trophy"])}" fill="none" stroke="{colour}" stroke-width="1.9" stroke-linecap="round" '
                  f'stroke-linejoin="round" transform="translate({tx + 21:.1f},{ty + th / 2 - 9}) scale(0.75)"/>',
                  text(tx + 58, ty + 25, t["name"], 13.5, FG, 600),
                  label(tx + 58, ty + 42, t["tech"], MUTED, 9)]
    return "".join(parts)


def garage(x, y, w, categories: list[dict]) -> tuple[str, int]:
    """The tech stack as a parts list: one block per category, dark chips that wrap onto new lines."""
    chip_h, line_gap, chips_x, right = 30, 8, x + 210, x + w - 20
    parts, ry = [], y + 70
    for r, cat in enumerate(categories):
        if r:
            parts.append(f'<rect x="{x + 20}" y="{ry - 9}" width="{w - 40}" height="1" fill="{LINE}"/>')
        parts += [f'<rect x="{x + 20}" y="{ry + 11}" width="3" height="10" rx="1.5" fill="{ACCENTS[r % len(ACCENTS)]}"/>',
                  label(x + 32, ry + 20, cat["category"], MUTED, 9.5)]
        cx, line_y = chips_x, ry
        for item in cat["items"]:
            tw = item.get("text_width", len(item["label"]) * 9.5) * 0.74
            cw = tw + (40 if item.get("icon") else 24)
            if cx + cw > right and cx > chips_x:                      # no room left on this line
                cx, line_y = chips_x, line_y + chip_h + line_gap
            colour = readable(item.get("colour") or FG)
            parts.append(f'<rect x="{cx:.1f}" y="{line_y}" width="{cw:.1f}" height="{chip_h}" rx="15" fill="{INK}" stroke="{LINE}"/>')
            if item.get("icon"):
                parts.append(f'<path d="{item["icon"]}" fill="{colour}" transform="translate({cx + 12:.1f},{line_y + 8}) scale({14 / 24:.4f})"/>')
                parts.append(text(cx + 32, line_y + 19.5, item["label"], 12, FG, 500))
            else:
                parts.append(f'<circle cx="{cx + 14:.1f}" cy="{line_y + 15}" r="3" fill="{colour}"/>' + text(cx + 22, line_y + 19.5, item["label"], 12, FG, 500))
            cx += cw + 8
        ry = line_y + chip_h + 20
    h = ry - y
    return panel(x, y, w, h, "Garage", "Parts fitted to the car") + "".join(parts), h


SNAKE_PALETTE = {"--cb": "#00000000", "--cs": PINK, "--ce": "#232327",
                 "--c0": "#232327", "--c1": "#1F4A47", "--c2": "#2E7770", "--c3": "#45A39A", "--c4": TEAL}


def recolour_snake(svg: str) -> str:
    """Swap the snake's CSS colour variables for the dashboard palette, so the workflow's colour flags don't matter."""
    block = ";".join(f"{k}:{v}" for k, v in SNAKE_PALETTE.items())
    return re.sub(r":root\{[^}]*\}", ":root{" + block + "}", svg, count=1)


def track_map(x, y, w, snake_svg: str) -> tuple[str, int]:
    """The contribution snake, drawn as the circuit."""
    snake_svg = recolour_snake(snake_svg)
    root = re.search(r"<svg\b[^>]*>", snake_svg)
    view = re.search(r'viewBox="([^"]+)"', root.group(0)) if root else None
    if not root or not view:
        raise RuntimeError("Snake file is not in the expected SVG format")
    _, _, vw, vh = (float(v) for v in view.group(1).split())
    inner = snake_svg[root.end(): snake_svg.rindex("</svg>")]
    sw = w - 40
    sh = round(sw * vh / vw)
    sy = y + 56
    parts = [f'<svg x="{x + 20}" y="{sy}" width="{sw}" height="{sh}" viewBox="{view.group(1)}">{inner}</svg>']

    h = sy + sh + 12 - y
    return panel(x, y, w, h, "Track map", "Contribution calendar · last 12 months") + "".join(parts), h


def footer(y, synced: str, login: str) -> tuple[str, int]:
    return (label(20, y + 16, f"LAST SYNC {synced}", MUTED, 9) +
            label(W - 20, y + 16, f"REBUILT EVERY 12H · @{login}", MUTED, 9, "end")), 34


def build_bottom(content: dict, y: int, events: list[dict], snake_svg: str, synced: str, login: str) -> tuple[str, int]:
    row_h = 290
    parts = [system_logs(20, y, HALF, row_h, events), team_radio(20 + HALF + GAP, y, HALF, row_h, content["radio_messages"])]
    y += row_h + GAP
    parts.append(trophies(20, y, W - 40, 210, content["trophies"]))
    y += 210 + GAP
    g, gh = garage(20, y, W - 40, content["tech_stack"])
    parts.append(g)
    y += gh + GAP
    t, th = track_map(20, y, W - 40, snake_svg)
    parts.append(t)
    y += th + 6
    f, fh = footer(y, synced, login)
    parts.append(f)
    return "\n".join(parts), y + fh


def build(content: dict, stats: dict, streaks: dict, grade: str, percentile: float, daily: list[int], year_total: int,
          events: list[dict], snake_svg: str, synced: str, login: str) -> str:
    """The whole profile image, top to bottom."""
    top, y = build_top(content, stats, streaks, grade, percentile, daily, year_total, events)
    bottom, height = build_bottom(content, y, events, snake_svg, synced, login)
    p = content["profile"]
    summary = (f'{p["full_name"]}, number {p["race_number"]}: GitHub mission-control dashboard. '
               f'{stats["commits"]} commits, {stats["stars"]} stars, {stats["prs"]} pull requests, '
               f'{streaks["total"]} contributions, current streak {streaks["current"]["length"]} days, grade {grade}. '
               + "Top languages: " + ", ".join(f'{l["name"]} {l["percent"]:.0f}%' for l in stats["languages"][:3]) + ". "
               + "Tech stack: " + "; ".join(f'{c["category"]}: {", ".join(i["label"] for i in c["items"])}' for c in content["tech_stack"]) + ".")
    return document(top + "\n" + bottom, height + 6, summary)



def mark_uri() -> str:
    return "data:image/png;base64," + base64.b64encode(BRAND_MARK.read_bytes()).decode("ascii")


def photo_uri() -> str:
    """The photo as a base64 data URI: README SVGs cannot load external images."""
    return "data:image/jpeg;base64," + base64.b64encode(CAR_PHOTO.read_bytes()).decode("ascii")


def defs() -> str:
    return f'''<defs>
    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    <linearGradient id="loadbar" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="{CORAL}"/><stop offset="1" stop-color="{PINK}"/></linearGradient>
    <filter id="feather" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="34"/></filter>
    <mask id="photofade" maskUnits="userSpaceOnUse" x="0" y="0" width="{PHOTO_W}" height="{PHOTO_H}">
      <rect x="70" y="60" width="{PHOTO_W - 140}" height="{PHOTO_H - 120}" rx="160" fill="#fff" filter="url(#feather)"/>
    </mask>
    <mask id="rwmask" maskUnits="userSpaceOnUse"><image href="{mark_uri()}" x="0" y="0" width="{MARK_W}" height="{MARK_H}"/></mask>
    <g id="carphoto"><image href="{photo_uri()}" width="{PHOTO_W}" height="{PHOTO_H}" preserveAspectRatio="none" mask="url(#photofade)"/></g>
  </defs>'''


def document(body: str, height: int, title: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height}" width="{W}" height="{height}" role="img" aria-label="{esc(title)}">'
            f'<title>{esc(title)}</title>{defs()}<rect width="{W}" height="{height}" rx="18" fill="{BG}"/>{body}</svg>')
