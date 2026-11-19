"""Generate banner.html for the README banner.

Marks sit on concentric rings; their size traces one spiral arm. The big
marks are the MCP logo and client logos, the small ones stay dots.
The optional argument is the spiral phase in turns (0..1), for animation.

Render (2x, from a 1280x640 layout):
    python banner.py
    chrome --headless=new --hide-scrollbars --virtual-time-budget=5000 \\
        --force-device-scale-factor=2 --window-size=1280,640 \\
        --screenshot=banner.png banner.html

Animate (banner.webp, 4 s loop): write banner.build(i / 96) for i in 0..95,
screenshot each at 1x, then
    ffmpeg -framerate 24 -i %03d.png -c:v libwebp -quality 90 \\
        -compression_level 6 -loop 0 banner.webp
"""

import math
import re
import sys

W, H = 1280, 640
CX, CY = 1050, 320
STEP = 20  # ring spacing = mark pitch along each ring
PITCH = 165  # radial distance per spiral turn
REACH = 470  # radius where the arm fades out
LOGOS = ["modelcontextprotocol", "claude", "openai", "googlegemini", "githubcopilot", "cursor"]


def _path(name):
    return re.search(r' d="([^"]+)"', open(f"logos/{name}.svg").read()).group(1)


def build(phase=0.0):
    symbols = "".join(
        f'<symbol id="{n}" viewBox="0 0 24 24"><path d="{_path(n)}"/></symbol>' for n in LOGOS
    )
    # Three glow bands so the core burns brighter than the tail.
    bands = {"core": [], "mid": [], "tail": []}
    field = []
    for k in range(1, 56):
        r = k * STEP
        count = round(2 * math.pi * r / STEP)
        for j in range(count):
            a = 2 * math.pi * j / count
            x, y = CX + r * math.cos(a), CY + r * math.sin(a)
            if not (-10 < x < W + 10 and -10 < y < H + 10):
                continue
            arm = 0.5 + 0.5 * math.cos(a - 2 * math.pi * (r / PITCH + phase))
            s = 9.8 * arm**1.3 * max(0.0, 1 - r / REACH) ** 0.6
            band = bands["core" if r < 170 else "mid" if r < 330 else "tail"]
            d = min(s * 2.1, STEP - 3)
            if d >= 9:
                logo = LOGOS[(k * 7919 + j * 104729) % len(LOGOS)]
                band.append(
                    f'<use href="#{logo}" x="{x - d / 2:.2f}" y="{y - d / 2:.2f}" width="{d:.2f}" height="{d:.2f}"/>'
                )
            elif s > 0.6:
                band.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{s:.2f}"/>')
            else:
                # The lattice carries on as a faint field, brighter near the spiral.
                t = max(0.0, 1 - r / 1200) ** 1.2
                field.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{0.78 + 0.55 * t:.2f}" fill-opacity="{0.08 + 0.17 * t:.3f}"/>'
                )

    def glow(name, blur, alpha):
        return f"""<filter id="{name}" x="-50%" y="-50%" width="200%" height="200%">
    <feGaussianBlur in="SourceGraphic" stdDeviation="{blur}" result="b"/>
    <feColorMatrix in="b" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 {alpha} 0" result="g"/>
    <feMerge><feMergeNode in="g"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>"""

    font = 'font-family="Space Grotesk" font-weight="500" font-size="96" letter-spacing="-4"'
    # dx pulls the h in: at this size the default fx-h gap reads loose.
    word = '<tspan fill="#ff4713">fx</tspan><tspan dx="-1">houdinimcp</tspan>'
    return f"""<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500&family=DM+Sans:opsz,wght@9..40,400&display=block" rel="stylesheet">
<style>html,body{{margin:0;width:{W}px;height:{H}px;overflow:hidden;background:#121110}}svg{{display:block}}</style>
</head><body>
<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<defs>
  {symbols}
  {glow("glow-core", 12, 0.5)}
  {glow("glow-mid", 10, 0.4)}
  {glow("glow-tail", 8, 0.3)}
  <filter id="knockout" x="-20%" y="-50%" width="140%" height="200%"><feGaussianBlur stdDeviation="7"/></filter>
  <!-- Fades the dots out behind the letters; the background is untouched. -->
  <mask id="clear" maskUnits="userSpaceOnUse" x="0" y="0" width="{W}" height="{H}">
    <rect width="{W}" height="{H}" fill="white"/>
    <text x="92" y="318" {font} fill="black" stroke="black" stroke-width="18" stroke-linejoin="round" filter="url(#knockout)">fx<tspan dx="-1">houdinimcp</tspan></text>
  </mask>
  <filter id="grain"><feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="1" stitchTiles="stitch"/><feColorMatrix values="0 0 0 0 1  0 0 0 0 0.96  0 0 0 0 0.9  0 0 0 0.055 0"/></filter>
</defs>
<rect width="{W}" height="{H}" fill="#121110"/>
<g fill="#f1ebe3" mask="url(#clear)">{"".join(field)}</g>
<g fill="#ff4713" mask="url(#clear)">
  <g filter="url(#glow-tail)">{"".join(bands["tail"])}</g>
  <g filter="url(#glow-mid)">{"".join(bands["mid"])}</g>
  <g filter="url(#glow-core)">{"".join(bands["core"])}</g>
</g>
<text x="92" y="318" {font} fill="none" filter="url(#glow-mid)">{word}</text>
<text x="92" y="318" {font} fill="#f1ebe3">{word}</text>
<text x="97" y="360" font-family="DM Sans" font-size="22" fill="#b9b1a7">An MCP server for SideFX Houdini</text>
<rect width="{W}" height="{H}" filter="url(#grain)"/>
</svg></body></html>"""


if __name__ == "__main__":
    phase = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
    with open("banner.html", "w", encoding="utf-8") as fh:
        fh.write(build(phase))
