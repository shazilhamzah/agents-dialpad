import os
import math

# We will test geometries for Concept A, B, and C
out_dir = r"c:\Users\MuhammadShazil\Documents\dialtone\branding\concepts"

# Concept A: The Resonant D
# Canvas 256x256
# Stem: x=56..96, y=32..224 (width 40)
# Center: (96, 128)
# Outer arc: R=96 (y=32..224, right=192).
# Let's adjust center so total width is centered:
# Width of outer D: stem left is x=52. Stem right is x=96 (width 44).
# Center of arc: (96, 128). Outer R = 96.
# Right edge = 96 + 96 = 192.
# Width = 192 - 52 = 140. Centered: (256-140)/2 = 58.
# So stem x: 58 to 102 (width 44). Center: (102, 128). R_outer = 96. Right edge = 198.
# Total width = 198 - 58 = 140. Left pad = 58, right pad = 58.
# Height = 192 (32 to 224). Top pad = 32, bottom pad = 32.

# In the bowl, we carve two concentric crescent apertures:
# Aperture 1: between R=70 and R=52 (width 18)
# Aperture 2: inner counter from R=32 down to 0, or an inner hole of R=32.
# Even better: 
# Outer contour: M 58 32 H 102 A 96 96 0 0 1 102 224 H 58 Z
# Cutout 1 (acoustic slot): arc from (102, 58) to (102, 198) with R=70, thickness 18, so inner arc is R=52
# Cutout 2 (inner counter): semicircle with R=32 centered at (102, 128), from (102, 96) to (102, 160)

# Let's write an exact SVG path for Concept A:
svg_a = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256" role="img" aria-labelledby="title-a">
  <title id="title-a">Dialtone Logo Concept A - The Resonant D</title>
  <!-- Outer D silhouette minus acoustic slots, constructed as a single compound path (evenodd) -->
  <path fill="#09090b" fill-rule="evenodd" d="
    M 56 32
    H 104
    A 96 96 0 0 1 104 224
    H 56
    Z
    M 104 56
    A 72 72 0 0 1 104 200
    H 96
    A 60 60 0 0 0 96 68
    H 104
    Z
    M 104 88
    A 40 40 0 0 1 104 168
    H 96
    A 28 28 0 0 0 96 100
    H 104
    Z
  "/>
</svg>'''

with open(os.path.join(out_dir, "test_concept_a_v1.svg"), "w", encoding="utf-8") as f:
    f.write(svg_a)

print("Saved test_concept_a_v1.svg")
