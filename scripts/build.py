#!/usr/bin/env python3
"""regenerates assets/neofetch.svg and the live sections of README.md.

stdlib only. reads public github data, reports only what has already happened.
"""
import datetime as dt
import html
import json
import os
import re
import textwrap
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

USER = os.environ.get("GH_USER", "mishtiiikrishnaa")
TOKEN = os.environ.get("GITHUB_TOKEN")
ROOT = Path(__file__).resolve().parent.parent
NOW = dt.datetime.now(dt.timezone.utc)

# palette built around #FFA6C9
BG, BORDER = "#1c1420", "#3a2b40"
FG, DIM = "#f4e9f1", "#8f7d98"
PINK = "#FFA6C9"
PALETTE = ["#FFA6C9", "#FF7FAE", "#FFCBA4", "#FFE8A3", "#B8E6D0", "#A8D8F0", "#CDB4F6", "#E9C6F2"]


# ------------------------------------------------------------------ data
def api(path):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{USER}-profile-readme",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(f"https://api.github.com{path}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except (urllib.error.URLError, TimeoutError) as e:
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
    months = (NOW.year - t.year) * 12 + NOW.month - t.month - (NOW.day < t.day)
    months = max(months, 0)
    y, m = divmod(months, 12)
    if y:
        return f"{y}y {m}mo"
    if m:
        return f"{m}mo"
    return f"{(NOW - t).days}d"


def spark(counts):
    bars = "▁▂▃▄▅▆▇█"
    mx = max(counts) or 1
    return "".join("·" if c == 0 else bars[min(7, 1 + int(c / mx * 6.999))] for c in counts)


def clip(s, n):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


user = api(f"/users/{USER}")
if not user:
    raise SystemExit("could not reach the github api; leaving files untouched")

repos = api(f"/users/{USER}/repos?per_page=100&type=owner&sort=pushed") or []
repos = [r for r in repos if not r["fork"] and r["name"].lower() != USER.lower()]
repos.sort(key=lambda r: r["pushed_at"] or "", reverse=True)

events = api(f"/users/{USER}/events/public?per_page=100") or []
days = [(NOW - dt.timedelta(days=i)).date() for i in range(13, -1, -1)]
push_by_day = Counter(parse(e["created_at"]).date() for e in events if e["type"] == "PushEvent")
pushes = [push_by_day.get(d, 0) for d in days]

stars = sum(r["stargazers_count"] for r in repos)
langs = Counter(r["language"] for r in repos if r["language"])
lang_total = sum(langs.values()) or 1

last_words, last_repo = None, None
if repos:
    last_repo = repos[0]
    c = api(f"/repos/{USER}/{last_repo['name']}/commits?per_page=1")
    if c:
        last_words = c[0]["commit"]["message"].split("\n")[0].strip()

quotes = json.loads((ROOT / "quotes.json").read_text(encoding="utf-8"))
quote = quotes[NOW.date().toordinal() % len(quotes)]

name = (user.get("name") or USER).lower()
handle = f"{name}@github"
orcid = (user.get("blog") or "")
orcid = orcid.split("orcid.org/")[-1] if "orcid.org/" in orcid else None


# ------------------------------------------------------------------ svg card
LOGO = {
    "m": [r"           ", r" _ __ ___  ", r"| '_ ` _ \ ", r"| | | | | |", r"|_| |_| |_|"],
    "i": [r" _ ", r"(_)", r"| |", r"| |", r"|_|"],
    "s": [r"     ", r" ___ ", r"/ __|", r"\__ \ ", r"|___/"],
    "h": [r" _     ", r"| |__  ", r"| '_ \ ", r"| | | |", r"|_| |_|"],
}


def logo_lines():
    rows = [""] * 5
    for ch in "mish":
        glyph = LOGO[ch]
        w = max(len(g) for g in glyph)
        for i in range(5):
            rows[i] += glyph[i].ljust(w)
    return rows


def esc(s):
    return html.escape(s, quote=True)


def build_svg():
    W = 920
    X_LOGO, X_KEY, X_VAL = 36, 340, 440
    LH = 23
    out, d = [], [0.0]

    def text(x, y, s, fill, extra=""):
        d[0] += 0.07
        out.append(
            f'<text x="{x}" y="{y}" fill="{fill}" class="l" style="animation-delay:{d[0]:.2f}s" '
            f'xml:space="preserve" {extra}>{esc(s)}</text>'
        )

    # --- terminal chrome
    y = 22
    out.append(f'<circle cx="28" cy="{y + 2}" r="6" fill="#FF7FAE"/>')
    out.append(f'<circle cx="50" cy="{y + 2}" r="6" fill="#FFE8A3"/>')
    out.append(f'<circle cx="72" cy="{y + 2}" r="6" fill="#B8E6D0"/>')
    out.append(f'<text x="{W / 2}" y="{y + 6}" fill="{DIM}" text-anchor="middle">{esc(handle)}: ~</text>')
    out.append(f'<line x1="0" y1="46" x2="{W}" y2="46" stroke="{BORDER}"/>')

    y = 78
    text(40, y, "$ neofetch", FG)
    y += 14

    # --- logo (left column)
    logo_top = y + 62
    for i, row in enumerate(logo_lines()):
        out.append(
            f'<text x="{X_LOGO}" y="{logo_top + i * 25}" fill="{PALETTE[i % len(PALETTE)]}" '
            f'class="l" style="animation-delay:{0.2 + i * 0.1:.2f}s;font-size:18px" xml:space="preserve">{esc(row)}</text>'
        )

    # --- info (right column)
    y += LH
    text(X_KEY, y, handle, PINK, 'font-weight="bold"')
    y += LH * 0.8
    text(X_KEY, y, "-" * len(handle), DIM)
    y += LH

    top_langs = langs.most_common(4)
    last = f"{ago(repos[0]['pushed_at'])} · {repos[0]['name']}" if repos else "nothing yet"
    fields = [
        ("os", clip(user.get("bio") or "student", 52)),
        ("uptime", span(user["created_at"])),
        ("repos", f"{len([r for r in repos])} public, {stars} star{'s' if stars != 1 else ''} earned"),
        ("langs", ", ".join(l.lower() for l, _ in top_langs) or "-"),
        ("last push", last),
        ("pushes 14d", f"{spark(pushes)}  ({sum(pushes)})"),
        ("followers", f"{user['followers']} · following {user['following']}"),
    ]
    if orcid:
        fields.append(("orcid", orcid))

    for k, v in fields:
        text(X_KEY, y, k, PINK, 'font-weight="bold"')
        text(X_VAL, y, v, FG)
        y += LH

    # --- language bar
    y += 6
    bx = X_KEY
    bw = W - 40 - X_KEY
    for i, (l, n) in enumerate(top_langs):
        w = bw * n / lang_total
        out.append(
            f'<rect x="{bx:.1f}" y="{y - 12}" width="{max(w - 3, 2):.1f}" height="12" rx="3" '
            f'fill="{PALETTE[(i * 2) % len(PALETTE)]}" class="l" style="animation-delay:{d[0] + 0.1 * i:.2f}s"/>'
        )
        bx += w
    y += 26

    # --- palette blocks, neofetch style
    for i, c in enumerate(PALETTE):
        out.append(
            f'<rect x="{X_KEY + i * 30}" y="{y - 14}" width="26" height="16" rx="3" fill="{c}" '
            f'class="l" style="animation-delay:{d[0] + 0.05 * i:.2f}s"/>'
        )
    y += 40

    # --- fortune
    text(40, y, "$ fortune", FG)
    y += LH + 4
    for line in textwrap.wrap(f"“{quote['text']}”", 78):
        text(60, y, line, FG, 'font-style="italic"')
        y += LH
    text(60, y, f"— {quote['by']}", PINK)
    y += LH * 1.6

    # --- last words
    if last_words and last_repo:
        text(40, y, "$ git log -1", FG)
        y += LH + 4
        text(60, y, clip(last_words, 80), FG)
        y += LH
        text(60, y, f"in {last_repo['name']}, {ago(last_repo['pushed_at'])}", DIM)
        y += LH * 1.6

    out.append(
        f'<text x="40" y="{y}" fill="{FG}">$ <tspan class="cur" fill="{PINK}">█</tspan></text>'
    )
    H = int(y + 28)

    head = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="neofetch-style summary of {esc(USER)}'s github, refreshed automatically">
<style>
text{{font-family:"CMU Typewriter Text","Latin Modern Mono","Courier New",ui-monospace,Menlo,monospace;font-size:14px}}
.l{{opacity:0;animation:in .45s ease-out forwards}}
@keyframes in{{from{{opacity:0;transform:translateY(3px)}}to{{opacity:1;transform:none}}}}
.cur{{animation:blink 1.1s steps(1) infinite}}
@keyframes blink{{50%{{opacity:0}}}}
@media (prefers-reduced-motion:reduce){{.l{{opacity:1;animation:none}}.cur{{animation:none}}}}
</style>
<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="14" fill="{BG}" stroke="{BORDER}"/>
"""
    return head + "\n".join(out) + "\n</svg>\n"


# ------------------------------------------------------------------ readme
def cell(s):
    return html.escape(s, quote=False).replace("|", "&#124;")


def recent_table():
    rows = ["| repo | what it is | lang | touched |", "|:--|:--|:--|--:|"]
    for r in repos[:5]:
        rows.append(
            f"| [**{r['name']}**]({r['html_url']}) "
            f"| {cell(clip(r['description'], 58)) or '—'} "
            f"| {cell((r['language'] or '—').lower())} "
            f"| {ago(r['pushed_at'])} |"
        )
    return "\n".join(rows)


def swap(text, tag, body, inline=False):
    pat = re.compile(rf"(<!--{tag}:START-->)(.*?)(<!--{tag}:END-->)", re.S)
    if not pat.search(text):
        raise SystemExit(f"README.md is missing the {tag} markers")
    sep = "" if inline else "\n"
    return pat.sub(lambda m: f"{m.group(1)}{sep}{body}{sep}{m.group(3)}", text)


def main():
    (ROOT / "assets").mkdir(exist_ok=True)
    (ROOT / "assets" / "neofetch.svg").write_text(build_svg(), encoding="utf-8")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    readme = swap(readme, "RECENT", recent_table())
    qtext = f"> *“{quote['text']}”*  \n> — {quote['by']}"
    readme = swap(readme, "QUOTE", qtext)
    if last_words and last_repo:
        lw = f"`{last_words.replace(chr(96), chr(39))}`  \nin [{last_repo['name']}]({last_repo['html_url']}), {ago(last_repo['pushed_at'])}"
    else:
        lw = "nothing pushed yet."
    readme = swap(readme, "LAST", lw)
    readme = swap(readme, "STAMP", NOW.strftime("%Y-%m-%d %H:%M utc"), inline=True)
    (ROOT / "README.md").write_text(readme, encoding="utf-8")
    print("refreshed", NOW.isoformat(timespec="seconds"))


if __name__ == "__main__":
    main()
