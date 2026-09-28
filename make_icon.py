"""Генерирует icon.ico: градиентный скруглённый квадрат с ресивером и 4 каналами."""

from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S))
grad = Image.new("RGBA", (S, S))
px = grad.load()
for y in range(S):
    for x in range(S):
        t = (x + y) / (2 * S)
        px[x, y] = (255, int(122 - 61 * t), int(24 + 95 * t), 255)
mask = Image.new("L", (S, S))
ImageDraw.Draw(mask).rounded_rectangle((8, 8, S - 8, S - 8), radius=60, fill=255)
img.paste(grad, (0, 0), mask)

d = ImageDraw.Draw(img)
w = 16
d.rounded_rectangle((52, 58, 204, 110), radius=18, outline="white", width=w)
for x in (74, 108, 148, 182):
    d.line((x, 110, x, 200), fill="white", width=w)
img.save("icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
