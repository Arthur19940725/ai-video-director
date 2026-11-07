#!/usr/bin/env python3
"""Draw storyboard colour-block sketches (template P3) from a JSON spec.

    sketch.py storyboard/sketch.json --out-dir storyboard/sketches_v1

For each shot it draws a 1920x1080 PNG (or the spec's "size") with the 38% / 62%
guides and the labelled blocks, then sheet.png and sheet_gray.png. It reports
blocks whose brightness is too close to the background: in black and white
they would merge, so the palette needs more light/dark contrast.

Spec: {"size": [1920, 1080], "shots": [{"id": "S01", "note": "...", "bg": "#1f2a44",
       "blocks": [{"label": "女孩", "color": "#f2b134", "x": 0.3, "y": 0.3, "w": 0.16, "h": 0.6}]}]}
x, y, w, h are fractions of the frame; x, y is the top-left corner.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # works under `python -I` too

from PIL import Image, ImageColor, ImageDraw  # noqa: E402

from frame_tools import contact_sheet, draw_guides, fail, font, new_path  # noqa: E402

DEFAULT_SIZE = (1920, 1080)
MIN_LUMA_DELTA = 40  # Rec.709 luma difference (0-255) below which a block may merge with the background
SHEET_COLS = 3


def luma(color: str) -> float:
    r, g, b = ImageColor.getrgb(color)[:3]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def text_color(fill: str) -> str:
    return "#111111" if luma(fill) > 140 else "#f5f5f5"


def draw_shot(shot: dict, size: tuple[int, int]) -> tuple[Image.Image, list[str]]:
    w, h = size
    canvas = Image.new("RGB", size, shot.get("bg", "#808080"))
    draw = ImageDraw.Draw(canvas)
    label_font, title_font = font(max(18, h // 30)), font(max(20, h // 24))
    warnings = []
    for block in shot.get("blocks", []):
        missing = {"label", "color", "x", "y", "w", "h"} - block.keys()
        if missing:
            fail(f"shot {shot.get('id')}: block {block} lacks {sorted(missing)}")
        box = (block["x"] * w, block["y"] * h, (block["x"] + block["w"]) * w, (block["y"] + block["h"]) * h)
        draw.rectangle(box, fill=block["color"], outline="#000000", width=2)
        draw.text((box[0] + 8, box[1] + 6), block["label"], fill=text_color(block["color"]), font=label_font)
        delta = abs(luma(block["color"]) - luma(shot.get("bg", "#808080")))
        if delta < MIN_LUMA_DELTA:
            warnings.append(f"{shot.get('id')}: '{block['label']}' luma delta {delta:.0f} < {MIN_LUMA_DELTA}")
    draw_guides(draw, w, h)
    title = f"{shot.get('id', '?')}  {shot.get('note', '')}".strip()
    draw.rectangle((0, h - h // 14, w, h), fill="#000000")
    draw.text((16, h - h // 14 + 8), title, fill="#ffffff", font=title_font)
    return canvas, warnings


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("spec")
    p.add_argument("--out-dir", required=True)
    a = p.parse_args()
    spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
    shots = spec.get("shots") or fail("spec has no shots")
    size = tuple(spec.get("size", DEFAULT_SIZE))
    out_dir = Path(a.out_dir)
    paths, gray_paths, warnings = [], [], []
    for shot in shots:
        image, shot_warnings = draw_shot(shot, size)
        warnings += shot_warnings
        path = new_path(out_dir / f"{shot['id']}.png")
        image.save(path)
        gray = new_path(out_dir / "gray" / f"{shot['id']}_gray.png")
        image.convert("L").save(gray)
        paths.append(path)
        gray_paths.append(gray)
    contact_sheet(paths, SHEET_COLS).save(new_path(out_dir / "sheet.png"))
    contact_sheet(gray_paths, SHEET_COLS).save(new_path(out_dir / "sheet_gray.png"))
    print(f"{len(paths)} sketches, {out_dir / 'sheet.png'}, {out_dir / 'sheet_gray.png'}")
    for line in warnings:
        print(f"LOW CONTRAST {line}")
    if not warnings:
        print("contrast check: every block differs from its background by at least " f"{MIN_LUMA_DELTA} luma levels")
    return 0


if __name__ == "__main__":
    sys.exit(main())
