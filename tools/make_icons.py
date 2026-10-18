# Builds app/icons/*.png (dark background, teal→blue ring). Run at deploy time.
import os
from PIL import Image, ImageDraw
S = 1024
img = Image.new('RGB', (S, S), (12, 17, 23))
d = ImageDraw.Draw(img)
c1, c2 = (0x67, 0xd3, 0xc4), (0x2b, 0x97, 0xf5)
cx = cy = S / 2; R = 300; w = 86
for i in range(720):
    t = i / 720; a0 = -90 + 360 * t
    col = tuple(int(c1[k] + (c2[k] - c1[k]) * (1 - abs(2 * t - 1))) for k in range(3))
    d.arc([cx - R, cy - R, cx + R, cy + R], a0, a0 + 0.8, fill=col, width=w)
os.makedirs('app/icons', exist_ok=True)
for n, s in [('icon-512.png', 512), ('icon-192.png', 192), ('apple-touch-icon.png', 180)]:
    img.resize((s, s), Image.LANCZOS).save('app/icons/' + n, optimize=True)
