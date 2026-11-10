import os
import math
from PIL import Image

out_dir = r"c:\Users\MuhammadShazil\Documents\dialtone\branding\concepts"

# ==============================================================================
# CONCEPT A: The Resonant D (Harmonic Letterform)
# ==============================================================================
# Stem: x=58..102 (width 44), y=32..224 (height 192)
# Arc center: (102, 128)
# Outer R = 96. (y: 32..224, right edge = 102 + 96 = 198)
# Total width = 198 - 58 = 140. Left margin = 58, right margin = 58.
# Total height = 224 - 32 = 192. Top margin = 32, bottom margin = 32.
#
# Concentric bowl geometry:
# 1. Outer rim: R=96 down to R=68 (thickness 28)
# 2. Acoustic gap (cutout 1): from R=68 down to R=48 (gap 20)
#    Starts at (102, 128 - 68 = 60), arcs to (102, 128 + 68 = 196) with R=68,
#    steps in to (102, 128 + 48 = 176), arcs back to (102, 128 - 48 = 80) with R=48,
#    steps out to (102, 60), close.
# 3. Resonant wave band: from R=48 down to R=28 (thickness 20)
# 4. Inner counter (cutout 2): from R=28 down to 0
#    Starts at (102, 128 - 28 = 100), arcs to (102, 128 + 28 = 156) with R=28,
#    closes straight along x=102 back to (102, 100).

svg_a = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256" role="img" aria-labelledby="title-a">
  <title id="title-a">Dialtone Logo - Concept A: The Resonant D</title>
  <path fill="#09090b" fill-rule="evenodd" d="
    M 58 32
    H 102
    A 96 96 0 0 1 102 224
    H 58
    Z
    M 102 60
    A 68 68 0 0 1 102 196
    V 176
    A 48 48 0 0 0 102 80
    V 60
    Z
    M 102 100
    A 28 28 0 0 1 102 156
    V 100
    Z
  "/>
</svg>'''

# ==============================================================================
# CONCEPT B: The Live Line (Continuous Hotline Monogram)
# ==============================================================================
# Lowercase 'd'
# Left margin = 54, right margin = 54 -> Width = 148 (x: 54..202)
# Top margin = 32, bottom margin = 32 -> Height = 192 (y: 32..224)
# Stem on right: x=170..202 (width 32), y=32..224 (height 192)
# Bowl on left: centered at (122, 148), outer radius 68, inner radius 36.
# Leftmost of bowl: 122 - 68 = 54. Bottom of bowl: 148 + 68 = 216.
# Stem bottom extends to 224 (a tiny 8px overshoot/foot).
# Inside the counter: A crisp, solid active pulse node (circle radius 18) centered at (122, 148).
# Gap around pulse node: 36 - 18 = 18px all around. Extremely balanced.

svg_b = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256" role="img" aria-labelledby="title-b">
  <title id="title-b">Dialtone Logo - Concept B: The Live Line</title>
  <path fill="#09090b" fill-rule="evenodd" d="
    M 170 32
    H 202
    V 224
    H 170
    V 198
    A 68 68 0 1 1 170 98
    V 32
    Z
    M 170 148
    A 36 36 0 1 0 170 148.01
    Z
  "/>
  <circle cx="122" cy="148" r="18" fill="#09090b"/>
</svg>'''

# ==============================================================================
# CONCEPT C: The Rotary Prompt (Tactile Symbol)
# ==============================================================================
# Outer ring: center (128, 128), outer R=92, inner R=54 (ring thickness 38).
# Centered in 256x256: margins L=36, R=36, T=36, B=36.
# Three agent dial-ports on the left arc:
# Angles: 145 deg, 180 deg, 215 deg.
# Port radius: 14.
# Port center radius: 73. (Outer wall = 92 - 87 = 5, wait! If ring thickness is 38: R_out=92, R_in=54.
# Let's place port centers at (92 + 54)/2 = 73.
# Then port radius 11 gives wall thickness (38 - 22)/2 = 8px on each side.)
# Even better: What if the ports are 3 distinct circular dots in a crescent arc inside an open dial?
# Let's make Concept C an iconic Rotary Dial with a Terminal Caret:
# Outer disc: R=92.
# Off-hook aperture: A 60-degree notch at top-right (from angle 30 to angle 90).
# Inner hub: Center circle R=32.
# 3 Agent ports: circular cutouts of R=14 at radius 63:
# Angles: 140, 180, 220.
# Center prompt chevron '>' in hub!

r_hub = 63
p1_x = round(128 + r_hub * math.cos(math.radians(140)), 1)
p1_y = round(128 + r_hub * math.sin(math.radians(140)), 1)
p2_x = round(128 + r_hub * math.cos(math.radians(180)), 1)
p2_y = round(128 + r_hub * math.sin(math.radians(180)), 1)
p3_x = round(128 + r_hub * math.cos(math.radians(220)), 1)
p3_y = round(128 + r_hub * math.sin(math.radians(220)), 1)

# Prompt caret in center:
# Vertex at (136, 128), top at (120, 114), bottom at (120, 142)

svg_c = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256" role="img" aria-labelledby="title-c">
  <title id="title-c">Dialtone Logo - Concept C: The Rotary Prompt</title>
  <path fill="#09090b" fill-rule="evenodd" d="
    M 128 36
    A 92 92 0 1 1 127.9 36
    Z
    M 128 78
    A 50 50 0 1 0 128.1 78
    Z
    M {p1_x} {p1_y - 12}
    A 12 12 0 1 0 {p1_x} {p1_y + 12}
    A 12 12 0 1 0 {p1_x} {p1_y - 12}
    Z
    M {p2_x} {p2_y - 12}
    A 12 12 0 1 0 {p2_x} {p2_y + 12}
    A 12 12 0 1 0 {p2_x} {p2_y - 12}
    Z
    M {p3_x} {p3_y - 12}
    A 12 12 0 1 0 {p3_x} {p3_y + 12}
    A 12 12 0 1 0 {p3_x} {p3_y - 12}
    Z
  "/>
  <!-- Central terminal prompt caret -->
  <path fill="#09090b" d="
    M 122 114
    L 136 128
    L 122 142
    L 128 148
    L 148 128
    L 128 108
    Z
  "/>
</svg>'''

with open(os.path.join(out_dir, "concept-a.svg"), "w", encoding="utf-8") as f:
    f.write(svg_a.strip())

with open(os.path.join(out_dir, "concept-b.svg"), "w", encoding="utf-8") as f:
    f.write(svg_b.strip())

with open(os.path.join(out_dir, "concept-c.svg"), "w", encoding="utf-8") as f:
    f.write(svg_c.strip())

print("Saved concept-a.svg, concept-b.svg, concept-c.svg")
