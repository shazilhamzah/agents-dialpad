import math
from PIL import Image

# Let's test the Prompt-D geometry:
# A capital D where the left side is a terminal prompt '>' and the right side is the curved bowl!
# Let's see:
# Prompt vertex points right at (112, 128) or points left?
# In terminal, prompt points right: >
# If the stem has a chevron cutout pointing right:
# Left edge is flat at x=48.
# At x=48, top is y=36, bottom is y=220.
# If the right edge of the stem has a chevron, or the left spine is a prompt chevron:
# Imagine: Chevron '>' on the left:
# Point is at (120, 128).
# Top leg goes to (56, 44).
# Bottom leg goes to (56, 212).
# And a circular bowl on the right connects (56, 44) to (56, 212), curving through (200, 128)!
# Inside that, the negative space is ALSO a chevron or circle!

print("Testing geometries...")
