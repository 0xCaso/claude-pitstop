"""Generates the README chart: /usr/bin/python3 assets/make_chart.py assets

Layout follows frame "E · Number inside chart" in design/claude-pitstop.pen.
"""
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
peaks = [i for i in range(TURNS - 1) if with_[i + 1] < with_[i]]

W, H = 880, 400
X0, X1, Y0, Y1 = 40, 712, 352, 40   # plot box: Y0 bottom, Y1 top
YMAX = 620_000
def x(t): return X0 + (X1 - X0) * t / (TURNS - 1)
def y(v): return Y0 - (Y0 - Y1) * v / YMAX

def points(xs, idx=None):
    idx = range(len(xs)) if idx is None else idx
    return ["%.1f,%.1f" % (x(i), y(xs[i])) for i in idx]

def line(xs):
    return "M" + " L".join(points(xs))

def under(xs):
    return line(xs) + " L%d,%d L%d,%dZ" % (X1, Y0, X0, Y0)

def between(top, bottom):
    return line(top) + " L" + " L".join(points(bottom, reversed(range(TURNS)))) + "Z"

THEMES = {
    "light": dict(surface="#fcfcfb", border="#e4e3df", ink="#0b0b0b", ink2="#52514e", muted="#8a8984",
                  a="#2a78d6", b="#eb6834", fa=0.25, fb=0.20),
    "dark": dict(surface="#1a1a19", border="#2e2e2c", ink="#ffffff", ink2="#c3c2b7", muted="#8f8e86",
                 a="#3987e5", b="#d95926", fa=0.30, fb=0.20),
}

def gradient(gid, color, top, offset):
    return ('<linearGradient id="%s" gradientUnits="userSpaceOnUse" x1="0" y1="%d" x2="0" y2="%d">'
            '<stop offset="%s" stop-color="%s" stop-opacity="%s"/>'
            '<stop offset="1" stop-color="%s" stop-opacity="0.02"/></linearGradient>'
            % (gid, Y1, Y0, offset, color, top, color))

def svg(t):
    p0 = peaks[0]
    dots = "".join('<circle cx="%.1f" cy="%.1f" r="9" fill="%s"/><circle cx="%.1f" cy="%.1f" r="6" fill="%s"/>'
                   % (x(i), y(with_[i]), t["surface"], x(i), y(with_[i]), t["a"]) for i in peaks)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">
<title id="t">pitstop: {saving:.0%} fewer tokens re-read</title>
<desc id="d">Context size per turn in an illustrative session of {TURNS} turns growing by 4K tokens a turn. Without pitstop it climbs to 600K. With pitstop it drops back to {RESUME // 1000}K each time it passes {FIRE // 1000}K, so about {saving:.0%} fewer tokens are re-read over the session.</desc>
<defs>{gradient("ga", t["a"], t["fa"], 0.55)}{gradient("gb", t["b"], t["fb"], 0)}</defs>
<style>
text {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: {t["ink2"]}; font-weight: 500; }}
.hero {{ font-size: 96px; font-weight: 700; letter-spacing: -2px; fill: {t["ink"]}; font-variant-numeric: tabular-nums; }}
.caption {{ font-size: 22px; }}
.label {{ font-size: 17px; font-weight: 600; fill: {t["ink"]}; }}
.tick {{ font-size: 15px; fill: {t["muted"]}; font-variant-numeric: tabular-nums; }}
</style>
<rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="16" fill="{t["surface"]}" stroke="{t["border"]}"/>
<line x1="{X0}" x2="{X1}" y1="{Y0}" y2="{Y0}" stroke="{t["border"]}" stroke-width="1.5"/>
<path d="{between(without, with_)}" fill="url(#gb)"/>
<path d="{under(with_)}" fill="url(#ga)"/>
<path d="{line(without)}" fill="none" stroke="{t["b"]}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>
<path d="{line(with_)}" fill="none" stroke="{t["a"]}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>
{dots}
<text x="{x(p0)-6:.1f}" y="{y(with_[p0])-12:.1f}" text-anchor="end" class="tick">{FIRE // 1000}K</text>
<text x="{x(p0+1)+10:.1f}" y="{y(RESUME)+16:.1f}" class="tick">{RESUME // 1000}K</text>
<text x="{X1+14}" y="{y(without[-1])+6:.1f}" class="label">without pitstop</text>
<text x="{X1+14}" y="{y(with_[-1])+6:.1f}" class="label">with pitstop</text>
<text x="52" y="141" class="hero">−{saving:.0%}</text>
<text x="60" y="180" class="caption">tokens re-read</text>
</svg>
'''

for name, theme in THEMES.items():
    (OUT / ("context-%s.svg" % name)).write_text(svg(theme), encoding="utf-8")
print("saving %.1f%%  with-pitstop end %dK" % (saving * 100, with_[-1] // 1000))
