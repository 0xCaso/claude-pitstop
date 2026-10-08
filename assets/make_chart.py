"""Generates the README chart: /usr/bin/python3 assets/make_chart.py assets"""
import sys
from pathlib import Path

OUT = Path(sys.argv[1])
START, STEP, TURNS = 20_000, 4_000, 146
FIRE, RESUME = 226_000, 70_000   # medians of 142 pitstops / 108 measured resumes (local log)

def session(pitstop):
    c, xs = START, []
    for _ in range(TURNS):
        xs.append(c)
        c += STEP
        if pitstop and c > FIRE:
            c = RESUME
    return xs

without, with_ = session(False), session(True)
saving = 1 - sum(with_) / sum(without)

W, H = 880, 470
X0, X1, Y0, Y1 = 76, 724, 380, 130   # plot box: Y0 bottom, Y1 top
YMAX = 600_000
def x(t): return X0 + (X1 - X0) * t / (TURNS - 1)
def y(v): return Y0 - (Y0 - Y1) * v / YMAX

def path(xs):
    return " ".join("%s%.1f,%.1f" % ("M" if i == 0 else "L", x(i), y(v)) for i, v in enumerate(xs))

def area(xs):
    return path(xs) + " L%.1f,%.1f L%.1f,%.1fZ" % (x(len(xs) - 1), Y0, x(0), Y0)

THEMES = {
    "light": dict(surface="#fcfcfb", border="#e4e3df", ink="#0b0b0b", ink2="#52514e", muted="#8a8984",
                  grid="#ecebe7", a="#2a78d6", b="#eb6834", fill=0.10),
    "dark": dict(surface="#1a1a19", border="#2e2e2c", ink="#ffffff", ink2="#c3c2b7", muted="#8f8e86",
                 grid="#2a2a28", a="#3987e5", b="#d95926", fill=0.16),
}

def svg(t):
    first_drop = next(i for i in range(1, TURNS) if with_[i] < with_[i - 1])
    g = []
    for v in (0, 200_000, 400_000, 600_000):
        g.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="%s"/>' % (X0, X1, y(v), y(v), t["grid"]))
        g.append('<text x="%d" y="%.1f" text-anchor="end" class="tick">%s</text>' % (X0 - 10, y(v) + 4, "%dK" % (v // 1000) if v else "0"))
    for n in (0, 25, 50, 75, 100, 125):
        g.append('<text x="%.1f" y="%d" text-anchor="middle" class="tick">%d</text>' % (x(n), Y0 + 20, n))
    g.append('<text x="%d" y="%d" class="tick">turns</text>' % (X1 + 10, Y0 + 20))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">
<title id="t">Every turn re-reads the whole context</title>
<desc id="d">Illustrative session of {TURNS} turns growing by 4K tokens per turn. Without pitstop the context climbs to about 600K. With pitstop it drops back to 70K every time it passes 226K, so about {saving:.0%} fewer tokens are re-read over the session.</desc>
<style>
text {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: {t["ink2"]}; }}
.title {{ font-size: 20px; font-weight: 650; fill: {t["ink"]}; }}
.sub {{ font-size: 13px; }}
.tick {{ font-size: 12px; fill: {t["muted"]}; font-variant-numeric: tabular-nums; }}
.label {{ font-size: 13px; font-weight: 600; fill: {t["ink"]}; }}
.note {{ font-size: 12px; }}
.hero {{ font-size: 34px; font-weight: 700; fill: {t["ink"]}; font-variant-numeric: tabular-nums; }}
</style>
<rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="12" fill="{t["surface"]}" stroke="{t["border"]}"/>
<text x="32" y="44" class="title">Every turn re-reads the whole context</text>
<text x="32" y="68" class="sub">Context size per turn in an illustrative session that grows by 4K tokens a turn</text>
<text x="{W-32}" y="50" text-anchor="end" class="hero">−{saving:.0%}</text>
<text x="{W-32}" y="70" text-anchor="end" class="sub">tokens re-read over {TURNS} turns</text>
<g transform="translate(32,96)">
  <rect x="0" y="-9" width="14" height="4" rx="2" fill="{t["b"]}"/><text x="22" y="-3" class="sub">Without pitstop</text>
  <rect x="140" y="-9" width="14" height="4" rx="2" fill="{t["a"]}"/><text x="162" y="-3" class="sub">With pitstop</text>
</g>
{"".join(g)}
<path d="{area(without)}" fill="{t["b"]}" fill-opacity="{t["fill"]}"/>
<path d="{area(with_)}" fill="{t["a"]}" fill-opacity="{t["fill"]}"/>
<line x1="{X0}" x2="{X1}" y1="{y(200_000):.1f}" y2="{y(200_000):.1f}" stroke="{t["muted"]}" stroke-width="1" stroke-dasharray="4 4"/>
<text x="{X0+8}" y="{y(200_000)-8:.1f}" class="note">threshold 200K</text>
<path d="{path(without)}" fill="none" stroke="{t["b"]}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
<path d="{path(with_)}" fill="none" stroke="{t["a"]}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
<line x1="{X0}" x2="{X1}" y1="{Y0}" y2="{Y0}" stroke="{t["border"]}"/>
<text x="{X1+10}" y="{y(without[-1])-2:.1f}" class="label">Without pitstop</text>
<text x="{X1+10}" y="{y(without[-1])+15:.1f}" class="note">{without[-1]//1000}K</text>
<text x="{X1+10}" y="{y(with_[-1])-2:.1f}" class="label">With pitstop</text>
<text x="{X1+10}" y="{y(with_[-1])+15:.1f}" class="note">{with_[-1]//1000}K</text>
<text x="{x(first_drop)+8:.1f}" y="{y(RESUME)+18:.1f}" class="note">pitstop at {FIRE//1000}K → resume at {RESUME//1000}K</text>
<text x="32" y="{H-38}" class="note">Trigger and resume sizes are the medians of 142 real pitstops (author's log, Sep–Oct 2026).</text>
<text x="32" y="{H-20}" class="note">Re-read tokens are the area under each line; the checkpoint and the files read after a resume are not counted.</text>
</svg>
'''

for name, theme in THEMES.items():
    (OUT / ("context-%s.svg" % name)).write_text(svg(theme), encoding="utf-8")
print("saving %.1f%%  with-pitstop end %dK" % (saving * 100, with_[-1] // 1000))
