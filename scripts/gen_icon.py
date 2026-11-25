"""生成 assets/icon-180.png —— 180x180 记忆图谱主题图标（纯标准库，无依赖）。

运行：python scripts/gen_icon.py
"""
from __future__ import annotations

import math
import os
import struct
import zlib


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_png(path: str, size: int, pixels) -> None:
    raw = b""
    for y in range(size):
        raw += b"\x00"  # filter type 0
        for x in range(size):
            raw += bytes(pixels[y][x])
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    data = (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(raw, 9))
            + _chunk(b"IEND", b""))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def main() -> None:
    size = 180
    cx = cy = 90.0
    r = 86.0

    top = (58, 91, 210, 255)      # 深蓝
    bottom = (124, 82, 214, 255)  # 紫

    # 记忆图谱节点（中心 1 + 外圈 5）
    nodes = [(cx, cy)]
    for k in range(5):
        ang = -math.pi / 2 + k * 2 * math.pi / 5
        nodes.append((cx + 52 * math.cos(ang), cy + 52 * math.sin(ang)))

    pixels = [[(0, 0, 0, 0) for _ in range(size)] for _ in range(size)]

    def in_circle(x, y):
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r

    def dist_to_segment(px, py, ax, ay, bx, by):
        vx, vy = bx - ax, by - ay
        wx, wy = px - ax, py - ay
        c1 = vx * wx + vy * wy
        c2 = vx * vx + vy * vy
        t = 0.0 if c2 == 0 else max(0.0, min(1.0, c1 / c2))
        dx, dy = px - (ax + t * vx), py - (ay + t * vy)
        return math.hypot(dx, dy)

    for y in range(size):
        for x in range(size):
            if not in_circle(x, y):
                continue
            t = y / (size - 1)
            bg = lerp(top, bottom, t)
            # 连线（半透明白）
            line_alpha = 0
            for i in range(1, len(nodes)):
                if dist_to_segment(x, y, cx, cy, *nodes[i]) < 2.2:
                    line_alpha = 150
                    break
            # 节点
            node_color = None
            for i, (nx, ny) in enumerate(nodes):
                nd = math.hypot(x - nx, y - ny)
                rad = 9 if i == 0 else 5
                if nd <= rad:
                    node_color = (255, 255, 255, 255) if i == 0 else (214, 224, 255, 255)
                    break
            if node_color:
                col = node_color
            elif line_alpha:
                col = (255, 255, 255, line_alpha)
            else:
                col = bg
            pixels[y][x] = col

    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "assets", "icon-180.png")
    write_png(out, size, pixels)
    print("generated", out)


if __name__ == "__main__":
    main()
