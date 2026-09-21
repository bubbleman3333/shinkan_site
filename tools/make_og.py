"""SNS 共有用の画像 static/og.png（1200x630）を作り直す。

画像ライブラリ（Pillow など）を増やしたくないので、PNG を自前で書き出す。
本棚に本が並んでいるだけの図なので、文字は入れない（フォントを持たないため）。
実行: python tools/make_og.py
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

W, H = 1200, 630
BG = (28, 92, 69)        # 深緑（サイトの --brand）
SHELF = (18, 64, 47)
BOOKS = [(244, 246, 244), (226, 234, 229), (180, 83, 9), (212, 224, 216), (245, 158, 11), (200, 214, 205)]


def png(path: Path, pixels: list[bytearray]) -> None:
    raw = b"".join(b"\x00" + bytes(row) for row in pixels)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b""))


def main() -> None:
    rows = [bytearray(BG * W) for _ in range(H)]

    def fill(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(W, x1), min(H, y1)
        blob = bytes(color) * (x1 - x0)
        for y in range(y0, y1):
            rows[y][x0 * 3:x1 * 3] = blob

    # 棚板
    for shelf_y in (300, 560):
        fill(0, shelf_y, W, shelf_y + 14, SHELF)

    # 本の背を並べる
    for shelf_top, shelf_y in ((120, 300), (380, 560)):
        x = 90
        i = 0
        while x < W - 90:
            width = 34 + (i * 13) % 46
            height = (shelf_y - shelf_top) - (i * 17) % 60
            color = BOOKS[i % len(BOOKS)]
            fill(x, shelf_y - height, x + width, shelf_y, color)
            x += width + 10
            i += 1

    out = Path(__file__).resolve().parent.parent / "static" / "og.png"
    png(out, rows)
    print(f"{out} を書き出した（{W}x{H}）")


if __name__ == "__main__":
    main()
