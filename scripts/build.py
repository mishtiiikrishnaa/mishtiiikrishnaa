#!/usr/bin/env python3
"""redraws assets/neofetch.svg: a fastfetch-style card for a github profile.

stdlib only. reads public github data (plus your contribution calendar, the same
numbers as the graph on your profile) and reports only what has already happened. the card embeds cmu typewriter text (sil ofl, see fonts/OFL.txt),
so every visitor sees the same typeface.

runs hourly from .github/workflows/refresh.yml.
"""
import base64
import datetime as dt
import html
import json
import os
import textwrap
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

USER = os.environ.get("GH_USER", "mishtiiikrishnaa")
# CARD_TOKEN is optional: a classic token with read:user, only needed if the default
# GITHUB_TOKEN cannot see your private contribution counts.
TOKEN = os.environ.get("CARD_TOKEN") or os.environ.get("GITHUB_TOKEN")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NOW = dt.datetime.now(dt.timezone.utc)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30), "IST")  # no dst, so a fixed offset is exact
LOCAL = NOW.astimezone(IST)
TODAY = LOCAL.date()  # "today" means today in india, not in greenwich

CADENCE = "hour"  # how often the workflow runs; used in the svg description, keep it in sync with the cron

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
def api(path, tries=3):
    """get json from the github api. retries a couple of times, because an hourly job meets more blips."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": f"{USER}-profile-card"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    for attempt in range(1, tries + 1):
        req = urllib.request.Request(f"https://api.github.com{path}", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            print(f"! {path} -> {e} (attempt {attempt}/{tries})")
            if attempt < tries:
                time.sleep(2 * attempt)
    return None


def graphql(query, variables, tries=3):
    """post a graphql query. the graphql api always needs a token, unlike the rest one."""
    if not TOKEN:
        print("! graphql needs GITHUB_TOKEN (or CARD_TOKEN) in the environment")
        return None
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": f"{USER}-profile-card",
    }
    body = json.dumps({"query": query, "variables": variables}).encode()
    for attempt in range(1, tries + 1):
        req = urllib.request.Request("https://api.github.com/graphql", data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            print(f"! graphql -> {e} (attempt {attempt}/{tries})")
            if attempt < tries:
                time.sleep(2 * attempt)
            continue
        if data.get("errors"):
            print(f"! graphql errors: {data['errors']}")
            return None
        return data.get("data")
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
    # exit 0 on purpose: a flaky api hour should leave the old card in place, not turn the workflow red
    print("could not reach the github api; leaving the card untouched")
    raise SystemExit(0)

repos = api(f"/users/{USER}/repos?per_page=100&type=owner&sort=pushed") or []
# empty repos have no pushed_at, which would crash the "last push" line, so they sit this one out
repos = [r for r in repos if not r["fork"] and r["name"].lower() != USER.lower() and r.get("pushed_at")]
repos.sort(key=lambda r: r["pushed_at"] or "", reverse=True)

# the contribution calendar: same numbers, same quartile colours as the graph on the profile.
# (the old events feed only showed public pushes and quietly dropped a lot of activity.)
CALENDAR_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount contributionLevel } }
      }
    }
  }
}
"""
LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}

cal = graphql(CALENDAR_QUERY, {"login": USER})
try:
    cal = cal["user"]["contributionsCollection"]["contributionCalendar"]
except (TypeError, KeyError):
    # without the calendar the card would show zeros and lie, so keep the old one instead
    print("could not read the contribution calendar; leaving the card untouched")
    raise SystemExit(0)

count_by_day, level_by_day = {}, {}
for _week in cal["weeks"]:
    for _day in _week["contributionDays"]:
        _date = dt.date.fromisoformat(_day["date"])
        count_by_day[_date] = _day["contributionCount"]
        level_by_day[_date] = LEVELS.get(_day["contributionLevel"], 0)
total_year = cal["totalContributions"]
contribs_14d = sum(count_by_day.get(TODAY - dt.timedelta(days=i), 0) for i in range(14))

# current streak: consecutive days with a contribution. if nothing yet today, count back from
# yesterday so the streak does not read 0 every morning.
_d = TODAY if count_by_day.get(TODAY) else TODAY - dt.timedelta(days=1)
streak = 0
while count_by_day.get(_d):
    streak += 1
    _d -= dt.timedelta(days=1)

# weekday with the most contributions over the last year
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
by_weekday = Counter()
for _day_date, _n in count_by_day.items():
    by_weekday[_day_date.weekday()] += _n
busiest = DAYS[by_weekday.most_common(1)[0][0]] if sum(by_weekday.values()) else "-"

stars = sum(r["stargazers_count"] for r in repos)
disk_kb = sum(r.get("size", 0) for r in repos)

# languages: one vote per repo, for the language github lists as that repo's main one.
# (counting bytes let a single huge .ipynb, which is mostly embedded output, outweigh everything.)
lang_count = Counter(r["language"] for r in repos if r["language"])
lang_total = sum(lang_count.values()) or 1
top_langs = lang_count.most_common(5)
LANG_SHORT = {"jupyter notebook": "jupyter"}  # shorter legend labels so they are not clipped

last_repo = repos[0] if repos else None
newest_repo = max(repos, key=lambda r: r["created_at"]) if repos else None
last_sha, last_msg = None, None
if last_repo:
    c = api(f"/repos/{USER}/{last_repo['name']}/commits?per_page=1")
    if c:
        last_sha = c[0]["sha"][:7]
        last_msg = c[0]["commit"]["message"].split("\n")[0]

quotes = json.loads((ROOT / "quotes.json").read_text(encoding="utf-8"))
quote = quotes[(NOW.date().toordinal() * 24 + NOW.hour) % len(quotes)]  # changes every hour

handle = clean(USER) + "@github"  # the full username; "mish" lives in the ascii logo and prompt pills
blog = user.get("blog") or ""
orcid = blog.split("orcid.org/")[-1] if "orcid.org/" in blog else None

# the figure: a punched card, as in the jacquard loom ada wrote about in the quote below.
# every row is one letter of CARD_TEXT in 8-bit ascii, o = hole, . = no hole. so it spells
# something if you can read binary. change the text (max ~6 letters) to change the card.
CARD_TEXT = "mish"
RAINBOW = [PINK, PEACH, BUTTER, MINT, AQUA, SKY, LILAC]
ART_LH = 22  # row spacing of the figure, px


def card_rows(text=CARD_TEXT):
    rows = ["  ".join("o" if bit == "1" else "." for bit in format(ord(c), "08b")) for c in text]
    inner = max(map(len, rows)) + 2
    art = [" " + "_" * inner + " ", "/" + " " * inner + "|"]
    art += ["| " + r.ljust(inner - 1) + "|" for r in rows]
    art.append("|" + "_" * inner + "|")
    return art


# ------------------------------------------------------------------ svg
def build_svg():
    W = 940
    PX = CW * FS  # width of one character at 14px
    LH = 21
    out, defs, kf = [], [], []
    clip_id = [0]
    t = [0.3]  # animation clock, seconds
    ENTER = 0.35  # beat between the last typed char and the output showing up
    READ = 0.8  # beat between an output and the next prompt

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

    def typed(x, y, s, start, appear):
        """a command typed one character at a time, like a real shell.

        every character is its own element that is invisible until its moment (css only, so it
        behaves the same in safari, chrome and firefox; no smil, no clip paths). the cursor shows up
        with the prompt, steps along with the typing and disappears when enter is pressed.
        """
        s = clean(s)
        n = len(s)
        step = 0.06
        dur = max(n, 1) * step
        for i, ch in enumerate(s):
            if ch == " ":
                continue
            out.append(
                f'<text x="{x + PX * i:.2f}" y="{y}" fill="{FG}" class="l" '
                f'style="animation-delay:{start + i * step:.2f}s" xml:space="preserve">{esc(ch)}</text>'
            )
        clip_id[0] += 1
        k = clip_id[0]
        enter = start + dur + ENTER
        kf.append(
            f"@keyframes mv{k}{{to{{transform:translateX({PX * n:.2f}px)}}}}"
            f"@keyframes cv{k}{{0%,99%{{opacity:1}}100%{{opacity:0}}}}"
        )
        out.append(
            f'<rect x="{x}" y="{y - 14}" width="2.4" height="19" rx="1" fill="{PINK}" class="typing" '
            f'style="opacity:0;animation:mv{k} {dur:.2f}s steps({max(n, 1)},start) {start:.2f}s forwards,'
            f'cv{k} {enter - appear:.2f}s linear {appear:.2f}s forwards"/>'
        )
        return dur

    def prompt(y, cmd, cursor=False):
        """powerlevel-style pill: mish | ~ | rainbow chevrons | clock, then a chevron."""
        h, tip, pad = 22, 11, 12
        y0 = y - 16
        mid = y0 + h / 2
        clock = LOCAL.strftime("%H:%M") + " ist"
        segs = [("mish", PINK, 4), ("~", PEACH, 1)]
        segs += [("", c, 0) for c in (BUTTER, MINT, AQUA, SKY)]
        segs += [(clock, LILAC, len(clock))]
        x, placed = 40, []
        for label, col, n in segs:
            w = (n * PX + 2 * pad) if label else 9
            placed.append((x, w, label, col))
            x += w
        t0 = t[0]  # the prompt prints instantly, like a real shell
        g = [f'<g {fade(t0)}>']
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
        if cmd:
            start = t0 + 0.6  # cursor idles at the prompt for a moment before typing
            dur = typed(tx, y, cmd, start, t0)
            t[0] = start + dur + ENTER  # enter pressed: the output prints now
        if cursor:
            # appears with its own prompt and blinks, waiting for the next command
            out.append(f'<rect x="{tx}" y="{y - 14}" width="2.4" height="19" rx="1" fill="{PINK}" class="cur" '
                       f'style="animation-delay:{t0:.2f}s"/>')

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
    art = card_rows()
    for i, row in enumerate(art):
        col = RAINBOW[round(i * (len(RAINBOW) - 1) / max(len(art) - 1, 1))]
        out.append(
            f'<text x="40" y="{top + 12 + i * ART_LH}" fill="{col}" class="l" '
            f'style="animation-delay:{body_t:.2f}s;font-size:19px" '
            f'xml:space="preserve">{esc(row)}</text>'
        )

    # left: push heatmap (13 weeks, sunday first, like github)
    hy = top + 12 + len(art) * ART_LH + 22
    text(40, hy, [("contributions, last 13 weeks", DIM)], body_t)
    today = TODAY
    start = today - dt.timedelta(days=(today.weekday() + 1) % 7) - dt.timedelta(weeks=12)
    pitch, cell = 18, 15
    for i in range(91):
        d = start + dt.timedelta(days=i)
        if d > today:
            continue
        lvl = level_by_day.get(d, 0)
        col, row = divmod(i, 7)
        out.append(
            f'<rect x="{40 + col * pitch}" y="{hy + 12 + row * pitch}" width="{cell}" height="{cell}" rx="3" '
            f'fill="{HEAT[lvl]}" {fade(body_t)}/>'
        )

    # left: language bar + legend
    ly = hy + 12 + 7 * pitch + 22
    bar_w = 13 * pitch - 3
    bx = 40.0
    segs = [(LANG_SHORT.get(n.lower(), n.lower()), b) for n, b in top_langs]
    for i, (name, b) in enumerate(segs):
        w = bar_w * b / lang_total
        out.append(f'<rect x="{bx:.1f}" y="{ly}" width="{max(w - 3, 3):.1f}" height="10" rx="3" '
                   f'fill="{LANG_COLOURS[i]}" {fade(body_t)}/>')
        bx += w
    for i, (name, b) in enumerate(segs):
        cx, cy = 40 + (i % 2) * 135, ly + 28 + (i // 2) * LH
        out.append(f'<rect x="{cx}" y="{cy - 9}" width="9" height="9" rx="2.5" fill="{LANG_COLOURS[i]}" '
                   f'{fade(body_t)}/>')
        text(cx + 15, cy, [(f"{clip(name, 10)} {b * 100 / lang_total:.0f}%", FG)], body_t)
    left_bottom = ly + 28 + ((len(segs) - 1) // 2) * LH

    # right: fastfetch fields
    X = 340
    y = top + 12
    d = body_t
    text(X, y, [(handle, PINK, True)], d)
    y += LH
    text(X, y, [("-" * len(handle), DIM)], d)
    y += LH
    # nothing about the actual machine: "os" is whatever the profile bio says you are
    # (so edit your bio on github to change it), "host" is where the card lives.
    group1 = [("os", clip(user.get("bio") or "student", 56)),
              ("host", clip(f"github.com/{USER}", 40)),
              ("uptime", span(user["created_at"])),
              ("packages", f"{len(repos)} repos")]
    group1.append(("cpu", ", ".join(n.lower() for n, _ in top_langs[:4]) or "-"))
    group1.append(("disk", f"{disk_kb / 1024:.1f} mb" if disk_kb >= 1024 else f"{disk_kb} kb"))
    if user.get("location"):
        group1.append(("location", clip(user["location"], 40)))
    if orcid:
        group1.append(("orcid", orcid))
    group2 = [
        ("stars", str(stars)),
        ("followers", str(user["followers"])),
        ("following", str(user["following"])),
        ("last push", f"{ago(last_repo['pushed_at'])} · {last_repo['name']}" if last_repo else "-"),
        ("contribs 14d", str(contribs_14d)),
        ("contribs 1y", str(total_year)),
        ("streak", f"{streak}d"),
        ("busiest day", busiest),
        ("newest repo", f"{clip(newest_repo['name'], 24)} · {ago(newest_repo['created_at'])}" if newest_repo else "-"),
    ]
    for k, v in group1 + group2:  # one block, no gap between the groups
        text(X, y, [(k, PINK, True), (": ", FG), (v, FG)], d)
        y += LH
    y += LH * 0.5
    # fastfetch colour blocks
    for r, row in enumerate((BLOCKS_1, BLOCKS_2)):
        for i, c in enumerate(row):
            out.append(f'<rect x="{X + i * 28}" y="{y - 12 + r * 15}" width="28" height="15" fill="{c}" '
                       f'{fade(d)}/>')
    right_bottom = y + 30
    t[0] = body_t + READ

    y = max(left_bottom, right_bottom) + 40

    # ---- $ fortune ada ---------------------------------------------------
    prompt(y, "fortune ada")
    y += LH + 8
    for line in textwrap.wrap(f"“{clean(quote['text'])}”", 108):
        text(60, y, [(line, FG)], t[0])
        y += LH
    text(60, y, [("— ada lovelace", PINK), (f" · {quote['src']}", DIM)], t[0])
    y += LH * 2
    t[0] += READ

    # ---- $ git log -1 ----------------------------------------------------
    if last_sha and last_repo:
        prompt(y, "git log -1 --oneline")
        y += LH + 8
        text(60, y, [(last_sha, PEACH), ("  " + clip(last_msg, 96), FG)], t[0])
        y += LH
        text(60, y, [(f"# {last_repo['name']}, {ago(last_repo['pushed_at'])}", DIM)], t[0])
        y += LH * 2
        t[0] += READ

    # ---- $ _ -------------------------------------------------------------
    prompt(y, "", cursor=True)
    text(W - 40, y, [("refreshed " + LOCAL.strftime("%Y-%m-%d %H:%M") + " ist", DIM)], t[0], anchor="end")
    H = int(y + 36)

    css = (
        font_css()
        + 'text{font-family:"CMU Typewriter Text",monospace;font-size:14px;font-weight:400}'
        + ".b{font-weight:700}"
        + ".l{opacity:0;animation:in .01s linear forwards}"
        + "@keyframes in{from{opacity:0}to{opacity:1}}"
        + ".cur{opacity:0;animation:blink 1.1s steps(1) infinite}"
        + "@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}"
        + "@media (prefers-reduced-motion:reduce){.l{opacity:1;animation:none}.cur{opacity:1;animation:none}"
        + ".typing{display:none}}"
        + "".join(kf)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
        f'aria-labelledby="t d">\n<title id="t">{esc(handle)}</title>'
        f'<desc id="d">a fastfetch-style summary of {esc(USER)} on github, redrawn every {CADENCE}</desc>\n'
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
