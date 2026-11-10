import os
import math
from PIL import Image

out_dir = r"c:\Users\MuhammadShazil\Documents\dialtone\branding\concepts"
os.makedirs(out_dir, exist_ok=True)

# -------------------------------------------------------------
# CONCEPT A: The Resonant D (Harmonic Letterform)
# A capital 'D' where the left stem is rock-solid and the bowl
# is formed by two concentric harmonic acoustic arcs (dial tone carrier).
# Stem: x=52..96, y=36..220 (width 44, height 184)
# Arc center: (96, 128)
# Outer R = 92 (y: 36..220, x_max: 96+92 = 188)
# Total width: 188 - 52 = 136. Centered in 256: pad = (256-136)/2 = 60.
# Let's shift x by +8:
# Stem: x=60..104 (width 44)
# Arc center: (104, 128)
# Outer R: 92 -> x_max = 196. Total width: 196 - 60 = 136.
# Left pad = 60, right pad = 60. Perfectly centered!
# Top pad = 36, bottom pad = 36. Perfectly centered!
# 
# Now the bowl cuts:
# We want two concentric acoustic bands.
# Band 1 (outer): from R=92 to R=64 (thickness 28).
# Acoustic gap: from R=64 to R=48 (gap 16).
# Band 2 (inner harmonic arc): from R=48 to R=20 (thickness 28).
# Inner core (counter): R < 20.
# Both bands anchor into the stem at x=104.
# Let's write this as one clean compound path:
# -------------------------------------------------------------
svg_a = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256" role="img" aria-labelledby="title-a">
  <title id="title-a">Dialtone Logo - Concept A: The Resonant D</title>
  <path fill="#09090b" fill-rule="evenodd" d="
    M 60 36
    H 104
    A 92 92 0 0 1 104 220
    H 60
    Z
    M 104 64
    A 64 64 0 0 1 104 192
    H 104
    A 48 48 0 0 0 104 80
    H 104
    Z
    M 104 108
    A 20 20 0 0 1 104 148
    H 104
    A 0 0 0 0 0 104 108
    Z
  "/>
</svg>'''

# Wait, in Cutout 2: M 104 108 A 20 20 0 0 1 104 148 H ...
# Let's make sure the inner counter is a clean half-circle:
# Cutout 1 is the crescent gap between R=64 and R=48:
# M 104 64 A 64 64 0 0 1 104 192 H 104 (wait, if it goes back with A 48 48 0 0 0 104 80: from 192 to 80 is 112, 2*48=96, mismatch!)
# Center is y=128:
# At y = 128 - 64 = 64, R=64. At y = 128 + 64 = 192, R=64.
# At y = 128 - 48 = 80, R=48. At y = 128 + 48 = 176, R=48.
# So from (104, 192) we go up to (104, 176), then A 48 48 0 0 0 104 80, then up to (104, 64), and close!
# And the inner counter: from (104, 108) [y=128-20] to (104, 148) [y=128+20], radius 20!

svg_a_fixed = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256" role="img" aria-labelledby="title-a">
  <title id="title-a">Dialtone Logo - Concept A: The Resonant D</title>
  <!-- Outer D + two concentric acoustic wave cutouts -->
  <path fill="#09090b" fill-rule="evenodd" d="
    M 60 36
    H 104
    A 92 92 0 0 1 104 220
    H 60
    Z
    M 104 64
    A 64 64 0 0 1 104 192
    V 176
    A 48 48 0 0 0 104 80
    V 64
    Z
    M 104 104
    A 24 24 0 0 1 104 152
    V 104
    Z
  "/>
</svg>'''

with open(os.path.join(out_dir, "concept_a_v1.svg"), "w", encoding="utf-8") as f:
    f.write(svg_a_fixed.strip())

# -------------------------------------------------------------
# CONCEPT B: The Rotary Node (Abstract / Tactile Dial)
# An iconic telephone dial wheel crossed with an AI dispatch node.
# A circular carrier ring with an open off-hook aperture (30 degrees at top right)
# containing three circular dial nodes (Claude, Antigravity, Codex)
# and a central terminal pulse caret/core.
# 
# Let's design it with pure geometry:
# Center: (128, 128)
# Outer circle R=96, Inner circle R=68 (ring thickness 28).
# Or a bold solid ring: R_out=96, R_in=56 (thickness 40).
# Carved with 3 tactile circular finger holes / dial ports:
# Three circles of radius 14 centered at:
# 1) Top: (128, 76)  [r=52, angle -90]
# 2) Left: (76, 128) [r=52, angle 180]
# 3) Bottom: (128, 180) [r=52, angle 90]
# And on the right: an open gap / off-hook gate from angle -30 to +30.
# -------------------------------------------------------------

# Let's also explore CONCEPT B variant: "The Hotline Loop" (Lowercase d formed by a phone cable / live line)
# A continuous, bold line (thickness 28) forming a lowercase 'd':
# - Ascender on the right: x=176, y from 36 down to 220.
# - The line loops to the left around a circular bowl centered at (108, 152) with radius 68.
# - At the top of the bowl (108, 84), it loops in or connects with a terminal prompt arrow.
# Let's test a geometric version of this!

svg_b_loop = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256" role="img" aria-labelledby="title-b">
  <title id="title-b">Dialtone Logo - Concept B: The Hotline Loop</title>
  <!-- Lowercase 'd' constructed as an unbroken live-line loop with a terminal prompt core -->
  <!-- Stem on right: x from 152 to 184 (width 32), y from 36 to 220 -->
  <!-- Bowl on left: centered at (116, 148), outer radius 72, inner radius 40 (thickness 32) -->
  <path fill="#09090b" fill-rule="evenodd" d="
    M 152 36
    H 184
    V 220
    H 152
    V 194
    A 72 72 0 1 1 152 102
    V 36
    Z
    M 152 148
    A 40 40 0 1 0 152 148.01
    Z
  "/>
  <!-- Central pulse node: an active signal core inside the counter -->
  <circle cx="116" cy="148" r="18" fill="#09090b"/>
</svg>'''

with open(os.path.join(out_dir, "concept_b_v1.svg"), "w", encoding="utf-8") as f:
    f.write(svg_b_loop.strip())

# -------------------------------------------------------------
# CONCEPT C: The Dial Matrix (DTMF / Three-Line Hub)
# Three horizontal signal lines (representing the 3 CLI agents: Claude, Antigravity, Codex)
# that sweep into a bold semi-circular phone dial / receiver bowl,
# fusing the "live line" with the dialtone receiver.
#
# Line 1 (top): y=72, x from 48 to 128, then curves down
# Line 2 (middle): y=128, x from 48 to 128
# Line 3 (bottom): y=184, x from 48 to 128, then curves up
# Or: A rotary telephone dial with 3 clean apertures, formed as a pure monolithic badge.
# Let's construct a precision Rotary Dial symbol:
# Outer disc: R=96, center (128, 128).
# Center hole: R=32.
# 3 circular apertures (the 3 agent lines) at radius R=64:
# Angle 1: -150 deg (top-left)
# Angle 2: 180 deg (middle-left)
# Angle 3: 150 deg (bottom-left)
# And on the right side: the rotary finger stop / index bracket!
# -------------------------------------------------------------

# Let's compute positions of the 3 apertures:
cx, cy = 128, 128
r_ap = 60
holes = []
for deg in [-135, 180, 135]:
    rad = math.radians(deg)
    hx = round(cx + r_ap * math.cos(rad), 1)
    hy = round(cy + r_ap * math.sin(rad), 1)
    holes.append((hx, hy))

svg_c_rotary = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256" role="img" aria-labelledby="title-c">
  <title id="title-c">Dialtone Logo - Concept C: The Rotary Hub</title>
  <!-- Outer rotary disc with central hub hole and 3 agent dial ports -->
  <path fill="#09090b" fill-rule="evenodd" d="
    M 128 32
    A 96 96 0 1 1 127.9 32
    Z
    M 128 92
    A 36 36 0 1 0 128.1 92
    Z
    M {holes[0][0]} {holes[0][1] - 16}
    A 16 16 0 1 0 {holes[0][0]} {holes[0][1] + 16}
    A 16 16 0 1 0 {holes[0][0]} {holes[0][1] - 16}
    Z
    M {holes[1][0]} {holes[1][1] - 16}
    A 16 16 0 1 0 {holes[1][0]} {holes[1][1] + 16}
    A 16 16 0 1 0 {holes[1][0]} {holes[1][1] - 16}
    Z
    M {holes[2][0]} {holes[2][1] - 16}
    A 16 16 0 1 0 {holes[2][0]} {holes[2][1] + 16}
    A 16 16 0 1 0 {holes[2][0]} {holes[2][1] - 16}
    Z
  "/>
  <!-- Finger stop / index mark at bottom-right (45 deg) -->
  <path fill="#09090b" d="M 172 172 L 208 208 L 194 222 L 158 186 Z"/>
</svg>'''

with open(os.path.join(out_dir, "concept_c_v1.svg"), "w", encoding="utf-8") as f:
    f.write(svg_c_rotary.strip())

print("Saved prototypes v1")
