# -*- coding: utf-8 -*-
import os, subprocess
from weasyprint import HTML

BASE = os.path.dirname(os.path.abspath(__file__))
pdf = os.path.join(BASE, "out.pdf")
HTML(os.path.join(BASE, "index.html")).write_pdf(pdf)
subprocess.run(["pdftoppm", "-r", "192", "-png", "-singlefile", pdf,
                os.path.join(BASE, "out")], check=True)

from PIL import Image
im = Image.open(os.path.join(BASE, "out.png")).convert("RGB")
w, h = im.size
px = im.load()
bg = px[5, h - 5]
bottom = h - 1
while bottom > 0:
    row = [px[x, bottom] for x in range(0, w, 7)]
    if any(abs(c[0] - bg[0]) + abs(c[1] - bg[1]) + abs(c[2] - bg[2]) > 12 for c in row):
        break
    bottom -= 1
im = im.crop((0, 0, w, min(h, bottom + 40)))
print("final size", im.size, "bg", bg)
im.save(os.path.join(BASE, "out.png"))
