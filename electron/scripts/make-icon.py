"""Generate a 1024x1024 app icon for Marketplace Appraiser.

Teal diamond on a dark rounded-rect background.
Usage: python make-icon.py
Output: ../build/icon.png
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math

SIZE = 1024
OUT = Path(__file__).parent.parent / "build" / "icon.png"

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# Background: dark rounded rectangle
bg_color = (30, 32, 40)
radius = 180
draw.rounded_rectangle([40, 40, SIZE - 40, SIZE - 40], radius=radius, fill=bg_color)

# Outer diamond (teal)
cx, cy = SIZE // 2, SIZE // 2
outer_r = 300
teal = (0, 128, 128)
diamond_outer = [
    (cx, cy - outer_r),
    (cx + outer_r, cy),
    (cx, cy + outer_r),
    (cx - outer_r, cy),
]
draw.polygon(diamond_outer, fill=teal)

# Inner diamond (cut-out, matches background)
inner_r = 180
diamond_inner = [
    (cx, cy - inner_r),
    (cx + inner_r, cy),
    (cx, cy + inner_r),
    (cx - inner_r, cy),
]
draw.polygon(diamond_inner, fill=bg_color)

# Center dot (teal)
dot_r = 60
draw.ellipse(
    [cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
    fill=teal,
)

OUT.parent.mkdir(parents=True, exist_ok=True)
img.save(str(OUT), "PNG")
print(f"Saved {OUT}")
