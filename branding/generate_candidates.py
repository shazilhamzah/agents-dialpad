import os
import math
from PIL import Image

out_dir = r"c:\Users\MuhammadShazil\Documents\dialtone\branding\concepts"

# ==============================================================================
# CANDIDATE 1: The Resonant D (Concept A)
# Monolithic capital D with dual-frequency resonant acoustic cuts.
# Stem: x=52..92 (width 40), y=36..220 (height 184)
# Bowl: center at (92, 128)
# Outer contour:
#   Top straight: (52, 36) to (104, 36)
#   Arc to (104, 220) with R=92
#   Bottom straight: (104, 220) to (52, 220)
#   Left straight: (52, 220) to (52, 36)
# Total width: (104 + 92) - 52 = 144. Centered: (256-144)/2 = 56.
# Let's shift by +4:
# Stem: x=56..96 (width 40).
# Arc center: (108, 128). Outer R=92.
# Rightmost: 108 + 92 = 200.
# Width = 200 - 56 = 144. Left pad = 56, right pad = 56.
# Top: 128 - 92 = 36. Bottom: 128 + 92 = 220. Top pad = 36, bottom pad = 36.
# Height = 184. Perfect square bounding footprint!
#
# Now for the counter and acoustic wave:
# Instead of multiple disjointed cuts, let's carve a bold, beautiful inner counter
# and a resonant concentric tone aperture:
# Outer bowl thickness: 32.
# Outer arc: R=92.
# Slot 1 (Acoustic wave gap): from R=60 down to R=44 (gap of 16).
# Inner tone band: from R=44 down to R=24 (thickness 20).
# Inner counter: R=24 down to 0.
# This creates a solid outer D rim (32px), a concentric acoustic wave band (20px),
# and an inner core aperture (48px diameter circle/semicircle)!
# ==============================================================================

svg_candidate_a = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256" role="img" aria-labelledby="title-a">
  <title id="title-a">Dialtone Logo - Concept A: The Resonant D</title>
  <!-- Single compound path with evenodd fill rule for clean vector outlines -->
  <path fill="#09090b" fill-rule="evenodd" d="
    M 56 36
    H 108
    A 92 92 0 0 1 108 220
    H 56
    Z
    M 108 68
    A 60 60 0 0 1 108 188
    V 172
    A 44 44 0 0 0 108 84
    V 68
    Z
    M 108 104
    A 24 24 0 0 1 108 152
    V 104
    Z
  "/>
</svg>'''

# ==============================================================================
# CANDIDATE 2: The Hotline d (Concept B)
# Lowercase 'd' formed by an unbroken "live line" cable/circuit.
# Stem on right: x=160..196 (width 36), y=36..220 (height 184).
# Bowl on left: centered at (114, 148), outer radius 72, inner radius 36 (thickness 36).
# Total width: 196 - (114 - 72) = 196 - 42 = 154.
# Centered in 256: pad = (256 - 154)/2 = 51.
# Let's shift by +9 to make it perfectly centered:
# Leftmost = 42 + 9 = 51.
# Center of bowl = (123, 148).
# Stem x = 169..205 (width 36). Rightmost = 205.
# Total width = 205 - 51 = 154. Left pad = 51, right pad = 51.
# Top: y=36. Bottom: y=220 (stem) and y=148+72=220 (bowl bottom)!
# Both stem and bowl sit exactly on baseline y=220!
# Height = 184 (y=36..220). Top pad = 36, bottom pad = 36.
# Inside the bowl: an open counter of radius 36.
# And inside the counter: a clean terminal prompt caret '>' or a live pulse dot!
# Let's make the counter clean and iconic, with a prompt caret '>' nestled in the core:
# Prompt caret in counter: centered at (123, 148), size 24.
# ==============================================================================

svg_candidate_b = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256" role="img" aria-labelledby="title-b">
  <title id="title-b">Dialtone Logo - Concept B: The Hotline d</title>
  <!-- Compound path: lowercase d with stem and circular bowl -->
  <path fill="#09090b" fill-rule="evenodd" d="
    M 169 36
    H 205
    V 220
    H 169
    V 194
    A 72 72 0 1 1 169 102
    V 36
    Z
    M 169 148
    A 36 36 0 1 0 169 148.01
    Z
  "/>
  <!-- Central active terminal prompt caret in the counter -->
  <path fill="#09090b" d="
    M 116 134
    L 130 148
    L 116 162
    L 122 168
    L 142 148
    L 122 128
    Z
  "/>
</svg>'''

# ==============================================================================
# CANDIDATE 3: The Rotary Hub / 3-Agent Pulse (Concept C)
# A bold, geometric rotary dial symbol.
# Outer circle: center (128, 128), outer radius 92, inner radius 56 (thickness 36).
# Off-hook aperture: a 60-degree notch at top-right (30 deg to 90 deg) or top.
# Three circular dial ports (Claude, Antigravity, Codex) spaced along the left arc:
# Port 1: at angle 150 deg (top left)
# Port 2: at angle 180 deg (left center)
# Port 3: at angle 210 deg (bottom left)
# And at the center: a prompt cursor / dial axle!
# Or: A monolithic dial with 3 clean circular apertures.
# Let's construct Candidate C with mathematical elegance:
# ==============================================================================

cx, cy = 128, 128
r_port = 74
p1_x = round(cx + r_port * math.cos(math.radians(150)), 1)
p1_y = round(cy + r_port * math.sin(math.radians(150)), 1)
p2_x = round(cx + r_port * math.cos(math.radians(180)), 1)
p2_y = round(cy + r_port * math.sin(math.radians(180)), 1)
p3_x = round(cx + r_port * math.cos(math.radians(210)), 1)
p3_y = round(cy + r_port * math.sin(math.radians(210)), 1)

# Let's make a modern interpretation:
# A circular telephone dial with an off-hook receiver break (top right)
# and three tactile agent ports:
svg_candidate_c = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256" role="img" aria-labelledby="title-c">
  <title id="title-c">Dialtone Logo - Concept C: The Rotary Hub</title>
  <!-- Outer ring R=92, inner R=54, with 3 circular agent ports and off-hook gap -->
  <path fill="#09090b" fill-rule="evenodd" d="
    M 128 36
    A 92 92 0 1 1 127.9 36
    Z
    M 128 74
    A 54 54 0 1 0 128.1 74
    Z
    M {p1_x} {p1_y - 14}
    A 14 14 0 1 0 {p1_x} {p1_y + 14}
    A 14 14 0 1 0 {p1_x} {p1_y - 14}
    Z
    M {p2_x} {p2_y - 14}
    A 14 14 0 1 0 {p2_x} {p2_y + 14}
    A 14 14 0 1 0 {p2_x} {p2_y - 14}
    Z
    M {p3_x} {p3_y - 14}
    A 14 14 0 1 0 {p3_x} {p3_y + 14}
    A 14 14 0 1 0 {p3_x} {p3_y - 14}
    Z
  "/>
  <!-- Central live-line horizontal carrier pulse bridging the hub -->
  <rect x="100" y="122" width="56" height="12" rx="6" fill="#09090b"/>
</svg>'''

with open(os.path.join(out_dir, "candidate_a.svg"), "w", encoding="utf-8") as f:
    f.write(svg_candidate_a.strip())

with open(os.path.join(out_dir, "candidate_b.svg"), "w", encoding="utf-8") as f:
    f.write(svg_candidate_b.strip())

with open(os.path.join(out_dir, "candidate_c.svg"), "w", encoding="utf-8") as f:
    f.write(svg_candidate_c.strip())

print("Saved candidates A, B, C")
