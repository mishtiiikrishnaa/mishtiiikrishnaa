#!/usr/bin/env python3
"""redraws assets/neofetch.svg: a fastfetch-style card for a github profile.

stdlib only. reads public github data and reports only what has already
happened. the card embeds cmu typewriter text (sil ofl, see fonts/OFL.txt),
so every visitor sees the same typeface.
"""
import base64
import datetime as dt
import html
import json
import os
import textwrap
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

USER = os.environ.get("GH_USER", "mishtiiikrishnaa")
TOKEN = os.environ.get("GITHUB_TOKEN")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NOW = dt.datetime.now(dt.timezone.utc)

# ---- things github cannot tell us; edit freely, keep them true ------------
SYSTEM = [
    ("os", "macos"),
    ("shell", "zsh"),
    ("terminal", "ghostty"),
    ("font", "cmu typewriter text"),
]

# ---- ghostty palette (from the real config) -------------------------------
BG, BORDER = "#0f0f12", "#2a2a2f"
FG, DIM = "#e8e8ed", "#7d7d88"
PINK, PINK_HI = "#ffa6c9", "#ff78a5"
PEACH, BUTTER, MINT, SKY, AQUA, LILAC = "#ffd6a6", "#ffe8c9", "#c9ffa6", "#a6c9ff", "#a6fff0", "#cdb4f6"
LANG_COLOURS = [PINK, PEACH, MINT, SKY, AQUA, LILAC]
HEAT = ["#1b1b21", "#4a2a3b", "#8f4768", PINK_HI, PINK]
BLOCKS_1 = [PINK_HI, MINT, PEACH, SKY, PINK, AQUA, FG, BORDER]
BLOCKS_2 = [PINK, "#e8ffd6", BUTTER, "#c9dfff", "#ffc9df", "#c9fff8", "#ffffff", "#3a3a40"]

CW = 0.525  # advance width of cmu typewriter text, in em
FS = 14


# ------------------------------------------------------------------ helpers
def api(path):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": f"{USER}-profile-card"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(f"https://api.github.com{path}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        print(f"! {path} -> {e}")
        return None


def parse(ts):
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def ago(ts):
    s = int((NOW - parse(ts)).total_seconds())
    for n, u in ((86400 * 365, "y"), (86400 * 30, "mo"), (86400, "d"), (3600, "h"), (60, "m")):
        if s >= n:
            return f"{s // n}{u} ago"
    return "just now"


def span(ts):
    t = parse(ts)
    months = max((NOW.year - t.year) * 12 + NOW.month - t.month - (NOW.day < t.day), 0)
    y, m = divmod(months, 12)
    if y:
        return f"{y}y {m}mo"
    return f"{m}mo" if m else f"{(NOW - t).days}d"


ALLOWED = set((HERE / "fonts" / "charset.txt").read_text(encoding="utf-8"))


def clean(s, collapse=True):
    """lowercase, and swap anything the embedded font lacks for '?'."""
    s = str(s).replace("\n", " ").replace("\t", " ")
    if collapse:
        s = " ".join(s.split())
    s = s.lower()
    return "".join(c if c in ALLOWED else "?" for c in s)


def clip(s, n):
    s = clean(s)
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def esc(s):
    return html.escape(s, quote=True)


def font_css():
    def b64(name):
        return base64.b64encode((HERE / "fonts" / name).read_bytes()).decode()

    face = (
        '@font-face{font-family:"CMU Typewriter Text";font-weight:%s;'
        'src:url(data:font/woff2;base64,%s) format("woff2")}'
    )
    return face % (400, b64("cmu-typewriter-regular.woff2")) + face % (700, b64("cmu-typewriter-bold.woff2"))


# ------------------------------------------------------------------ data
user = api(f"/users/{USER}")
if not user:
    raise SystemExit("could not reach the github api; leaving the card untouched")

repos = api(f"/users/{USER}/repos?per_page=100&type=owner&sort=pushed") or []
repos = [r for r in repos if not r["fork"] and r["name"].lower() != USER.lower()]
repos.sort(key=lambda r: r["pushed_at"] or "", reverse=True)

events = []
for page in (1, 2, 3):
    chunk = api(f"/users/{USER}/events/public?per_page=100&page={page}")
    if not chunk:
        break
    events += chunk
push_by_day = Counter(parse(e["created_at"]).date() for e in events if e["type"] == "PushEvent")
pushes_14d = sum(push_by_day.get(NOW.date() - dt.timedelta(days=i), 0) for i in range(14))

stars = sum(r["stargazers_count"] for r in repos)
disk_kb = sum(r.get("size", 0) for r in repos)

lang_bytes = Counter()
for r in repos[:25]:
    lang_bytes.update(api(f"/repos/{USER}/{r['name']}/languages") or {})
if not lang_bytes:
    lang_bytes = Counter(r["language"] for r in repos if r["language"])
lang_total = sum(lang_bytes.values()) or 1
top_langs = lang_bytes.most_common(5)

last_repo = repos[0] if repos else None
last_sha, last_msg = None, None
if last_repo:
    c = api(f"/repos/{USER}/{last_repo['name']}/commits?per_page=1")
    if c:
        last_sha = c[0]["sha"][:7]
        last_msg = c[0]["commit"]["message"].split("\n")[0]

quotes = json.loads((ROOT / "quotes.json").read_text(encoding="utf-8"))
quote = quotes[(NOW.date().toordinal() * 4 + NOW.hour // 6) % len(quotes)]  # changes every refresh

handle = clean(user.get("name") or USER) + "@github"
blog = user.get("blog") or ""
orcid = blog.split("orcid.org/")[-1] if "orcid.org/" in blog else None

LOGO = {
    "m": [r"           ", r" _ __ ___  ", r"| '_ ` _ \ ", r"| | | | | |", r"|_| |_| |_|"],
    "i": [r" _ ", r"(_)", r"| |", r"| |", r"|_|"],
    "s": [r"     ", r" ___ ", r"/ __|", r"\__ \ ", r"|___/"],
    "h": [r" _     ", r"| |__  ", r"| '_ \ ", r"| | | |", r"|_| |_|"],
}


def logo_rows():
    rows = [""] * 5
    for ch in "mish":
        g = LOGO[ch]
        w = max(map(len, g))
        for i in range(5):
            rows[i] += g[i].ljust(w)
    return rows


# ------------------------------------------------------------------ svg
def build_svg():
    W = 940
    PX = CW * FS  # width of one character at 14px
    LH = 21
    out, defs = [], []
    clip_id = [0]
    t = [0.3]  # animation clock, seconds

    def fade(delay):
        return f'class="l" style="animation-delay:{delay:.2f}s"'

    def text(x, y, spans, delay, size=None, anchor=None, extra=""):
        """spans: list of (string, colour[, bold])."""
        inner = ""
        for sp in spans:
            s, col = sp[0], sp[1]
            cls = ' class="b"' if len(sp) > 2 and sp[2] else ""
            inner += f'<tspan fill="{col}"{cls}>{esc(clean(s, collapse=False))}</tspan>'
        st = f"animation-delay:{delay:.2f}s" + (f";font-size:{size}px" if size else "")
        an = f' text-anchor="{anchor}"' if anchor else ""
        out.append(f'<text x="{x}" y="{y}" class="l" style="{st}"{an} xml:space="preserve" {extra}>{inner}</text>')

    def typed(x, y, s, delay):
        """a command that types itself out (smil; shows in full if smil is unsupported)."""
        s = clean(s)
        n = len(s)
        clip_id[0] += 1
        cid = f"c{clip_id[0]}"
        vals = ";".join(f"{PX * i:.2f}" for i in range(n + 1))
        defs.append(
            f'<clipPath id="{cid}"><rect x="{x}" y="{y - 15}" width="{PX * n + 4:.2f}" height="22">'
            f'<set attributeName="width" to="0" begin="0s" fill="freeze"/>'
            f'<animate attributeName="width" values="{vals}" calcMode="discrete" begin="{delay:.2f}s" '
            f'dur="{max(n, 1) * 0.045:.2f}s" fill="freeze"/></rect></clipPath>'
        )
        out.append(f'<text x="{x}" y="{y}" fill="{FG}" clip-path="url(#{cid})" xml:space="preserve">{esc(s)}</text>')
        return n * 0.045

    def prompt(y, cmd, cursor=False):
        """powerlevel-style pill: mish | ~ | rainbow chevrons | clock, then a chevron."""
        h, tip, pad = 22, 11, 12
        y0 = y - 16
        mid = y0 + h / 2
        clock = NOW.strftime("%H:%M") + " utc"
        segs = [("mish", PINK, 4), ("~", PEACH, 1)]
        segs += [("", c, 0) for c in (BUTTER, MINT, AQUA, SKY)]
        segs += [(clock, LILAC, len(clock))]
        x, placed = 40, []
        for label, col, n in segs:
            w = (n * PX + 2 * pad) if label else 9
            placed.append((x, w, label, col))
            x += w
        g = [f'<g {fade(t[0])}>']
        for i in range(len(placed) - 1, -1, -1):  # right to left so tips overlap the next segment
            sx, w, label, col = placed[i]
            if i == 0:
                d = (f"M{sx + 11},{y0} L{sx + w},{y0} L{sx + w + tip},{mid} L{sx + w},{y0 + h} "
                     f"L{sx + 11},{y0 + h} A11,11 0 0 1 {sx + 11},{y0} Z")
            else:
                d = f"M{sx},{y0} L{sx + w},{y0} L{sx + w + tip},{mid} L{sx + w},{y0 + h} L{sx},{y0 + h} Z"
            g.append(f'<path d="{d}" fill="{col}"/>')
        for sx, w, label, col in placed:
            if label:
                g.append(f'<text x="{sx + pad}" y="{y}" fill="{BG}" class="b" xml:space="preserve">{esc(label)}</text>')
        cx = x + tip + 14
        g.append(f'<polyline points="{cx},{y - 12} {cx + 6},{y - 5} {cx},{y + 2}" fill="none" stroke="{PINK}" '
                 f'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>')
        g.append("</g>")
        out.append("".join(g))
        tx = cx + 20
        dur = 0.0
        if cmd:
            dur = typed(tx, y, cmd, t[0] + 0.35)
        if cursor:
            out.append(f'<rect x="{tx}" y="{y - 14}" width="2.4" height="19" rx="1" fill="{PINK}" class="cur"/>')
        t[0] += 0.35 + dur + 0.25

    # ---- chrome ----------------------------------------------------------
    for i, c in enumerate((PINK_HI, PEACH, MINT)):
        out.append(f'<circle cx="{30 + i * 22}" cy="23" r="6" fill="{c}"/>')
    out.append(f'<text x="{W / 2}" y="28" fill="{DIM}" text-anchor="middle">{esc(handle)}: ~</text>')
    out.append(f'<line x1="0" y1="46" x2="{W}" y2="46" stroke="{BORDER}"/>')

    # ---- $ fastfetch -----------------------------------------------------
    prompt(86, "fastfetch")
    top = 130
    body_t = t[0]

    # left: logo
    for i, row in enumerate(logo_rows()):
        out.append(
            f'<text x="40" y="{top + 12 + i * 24}" fill="{[PINK, PEACH, BUTTER, MINT, SKY][i]}" class="l" '
            f'style="animation-delay:{body_t + i * 0.08:.2f}s;font-size:19px" '
            f'xml:space="preserve">{esc(row)}</text>'
        )

    # left: push heatmap (13 weeks, sunday first, like github)
    hy = top + 12 + 5 * 24 + 22
    text(40, hy, [("pushes, last 13 weeks", DIM)], body_t + 0.5)
    today = NOW.date()
    start = today - dt.timedelta(days=(today.weekday() + 1) % 7) - dt.timedelta(weeks=12)
    mx = max([push_by_day.get(start + dt.timedelta(days=i), 0) for i in range(91)] + [1])
    pitch, cell = 18, 15
    for i in range(91):
        d = start + dt.timedelta(days=i)
        if d > today:
            continue
        c = push_by_day.get(d, 0)
        lvl = 0 if c == 0 else min(4, 1 + int((c - 1) * 3 / max(mx - 1, 1) + 0.0001))
        col, row = divmod(i, 7)
        out.append(
            f'<rect x="{40 + col * pitch}" y="{hy + 12 + row * pitch}" width="{cell}" height="{cell}" rx="3" '
            f'fill="{HEAT[lvl]}" {fade(body_t + 0.6 + col * 0.05)}/>'
        )

    # left: language bar + legend
    ly = hy + 12 + 7 * pitch + 22
    bar_w = 13 * pitch - 3
    bx = 40.0
    segs = [(n.lower(), b) for n, b in top_langs]
    for i, (name, b) in enumerate(segs):
        w = bar_w * b / lang_total
        out.append(f'<rect x="{bx:.1f}" y="{ly}" width="{max(w - 3, 3):.1f}" height="10" rx="3" '
                   f'fill="{LANG_COLOURS[i]}" {fade(body_t + 1.4 + i * 0.1)}/>')
        bx += w
    for i, (name, b) in enumerate(segs):
        cx, cy = 40 + (i % 2) * 135, ly + 28 + (i // 2) * LH
        out.append(f'<rect x="{cx}" y="{cy - 9}" width="9" height="9" rx="2.5" fill="{LANG_COLOURS[i]}" '
                   f'{fade(body_t + 1.5 + i * 0.1)}/>')
        text(cx + 15, cy, [(f"{clip(name, 10)} {b * 100 / lang_total:.0f}%", FG)], body_t + 1.5 + i * 0.1)
    left_bottom = ly + 28 + ((len(segs) - 1) // 2) * LH

    # right: fastfetch fields
    X = 340
    y = top + 12
    d = body_t
    text(X, y, [(handle, PINK, True)], d)
    y += LH
    text(X, y, [("-" * len(handle), DIM)], d + 0.05)
    y += LH
    host = clip(user.get("bio") or "student", 56)
    group1 = list(SYSTEM[:1]) + [("host", host), ("uptime", span(user["created_at"])),
                                 ("packages", f"{len(repos)} repos")] + list(SYSTEM[1:])
    group1.append(("cpu", ", ".join(n.lower() for n, _ in top_langs[:4]) or "-"))
    group1.append(("disk", f"{disk_kb / 1024:.1f} mb" if disk_kb >= 1024 else f"{disk_kb} kb"))
    if orcid:
        group1.append(("orcid", orcid))
    group2 = [
        ("stars", str(stars)),
        ("followers", str(user["followers"])),
        ("following", str(user["following"])),
        ("last push", f"{ago(last_repo['pushed_at'])} · {last_repo['name']}" if last_repo else "-"),
        ("pushes 14d", str(pushes_14d)),
    ]
    for grp in (group1, group2):
        for k, v in grp:
            d += 0.06
            text(X, y, [(k, PINK, True), (": ", FG), (v, FG)], d)
            y += LH
        y += LH * 0.5
    # fastfetch colour blocks
    for r, row in enumerate((BLOCKS_1, BLOCKS_2)):
        for i, c in enumerate(row):
            out.append(f'<rect x="{X + i * 28}" y="{y - 12 + r * 15}" width="28" height="15" fill="{c}" '
                       f'{fade(d + 0.1 + i * 0.04)}/>')
    right_bottom = y + 30
    t[0] = d + 0.6

    y = max(left_bottom, right_bottom) + 40

    # ---- $ fortune ada ---------------------------------------------------
    prompt(y, "fortune ada")
    y += LH + 8
    for line in textwrap.wrap(f"“{clean(quote['text'])}”", 108):
        text(60, y, [(line, FG)], t[0])
        t[0] += 0.12
        y += LH
    text(60, y, [("— ada lovelace", PINK), (f" · {quote['src']}", DIM)], t[0])
    y += LH * 2

    # ---- $ git log -1 ----------------------------------------------------
    if last_sha and last_repo:
        prompt(y, "git log -1 --oneline")
        y += LH + 8
        text(60, y, [(last_sha, PEACH), ("  " + clip(last_msg, 96), FG)], t[0])
        y += LH
        text(60, y, [(f"# {last_repo['name']}, {ago(last_repo['pushed_at'])}", DIM)], t[0] + 0.1)
        y += LH * 2

    # ---- $ _ -------------------------------------------------------------
    prompt(y, "", cursor=True)
    text(W - 40, y, [("refreshed " + NOW.strftime("%Y-%m-%d %H:%M") + " utc", DIM)], t[0], anchor="end")
    H = int(y + 36)

    css = (
        font_css()
        + 'text{font-family:"CMU Typewriter Text",monospace;font-size:14px;font-weight:400}'
        + ".b{font-weight:700}"
        + ".l{opacity:0;animation:in .45s ease-out forwards}"
        + "@keyframes in{from{opacity:0}to{opacity:1}}"
        + ".cur{animation:blink 1.1s steps(1) infinite}"
        + "@keyframes blink{50%{opacity:0}}"
        + "@media (prefers-reduced-motion:reduce){.l{opacity:1;animation:none}.cur{animation:none}}"
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
        f'aria-labelledby="t d">\n<title id="t">{esc(handle)}</title>'
        f'<desc id="d">a fastfetch-style summary of {esc(USER)} on github, redrawn every six hours</desc>\n'
        f"<style>{css}</style>\n<defs>"
        f'<radialGradient id="glow" cx="85%" cy="0%" r="70%"><stop offset="0" stop-color="{PINK}" stop-opacity=".10"/>'
        f'<stop offset="1" stop-color="{PINK}" stop-opacity="0"/></radialGradient>' + "".join(defs) + "</defs>\n"
        f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="14" fill="{BG}" stroke="{BORDER}"/>\n'
        f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="14" fill="url(#glow)"/>\n'
        + "\n".join(out)
        + "\n</svg>\n"
    )


def main():
    (ROOT / "assets").mkdir(exist_ok=True)
    (ROOT / "assets" / "neofetch.svg").write_text(build_svg(), encoding="utf-8")
    print("redrew the card", NOW.isoformat(timespec="seconds"))


if __name__ == "__main__":
    main()
