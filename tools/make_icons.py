# Builds app/icons/*.png (black background, thin white ring, geometric L). Run at deploy time.
import os
from PIL import Image, ImageDraw
Q = 4; S = 1024 * Q
img = Image.new('RGB', (S, S), (0, 0, 0))
d = ImageDraw.Draw(img)
c = S / 2; R = 330 * Q; w = 30 * Q
d.ellipse([c - R, c - R, c + R, c + R], outline=(255, 255, 255), width=w)
x0, x1, y0, y1 = 410 * Q, 628 * Q, 330 * Q, 694 * Q; t = 46 * Q
d.polygon([(x0, y0), (x0 + t, y0), (x0 + t, y1 - t), (x1, y1 - t), (x1, y1), (x0, y1)], fill=(255, 255, 255))
img = img.resize((1024, 1024), Image.LANCZOS)
os.makedirs('app/icons', exist_ok=True)
for n, s in [('icon-512.png', 512), ('icon-192.png', 192), ('apple-touch-icon.png', 180)]:
    img.resize((s, s), Image.LANCZOS).save('app/icons/' + n, optimize=True)
