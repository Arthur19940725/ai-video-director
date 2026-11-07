#!/usr/bin/env python3
"""Image and frame checks for ai-video-director (Pillow + ffmpeg). Never overwrites a file.

info IMG...                      size, ratio, nearest standard ratio
fit IMG --ratio 16:9 [--size 1280x720] [--anchor 0.5,0.5] --out OUT
zoom IMG --factor 1.15 [--center 0.5,0.5] --out OUT      (push-in last frame)
patch ORIG EDITED --box x,y,w,h [--feather 12] --out OUT (paste an edited area back)
pair FIRST LAST --out-dir DIR    overlay + diff heatmap + 3x3 changed-pixel table + colour drift
gray IMG... --out-dir DIR        black-and-white copies (contrast check)
phone IMG [--width 390] --out OUT  phone-size preview
guides IMG --out OUT             draw the 38% / 62% lines
sheet IMG... --out OUT [--cols 4]  contact sheet with file names
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageStat

GUIDES = (0.38, 0.62)
RATIOS = {"16:9": 16 / 9, "9:16": 9 / 16, "4:3": 4 / 3, "3:4": 3 / 4, "1:1": 1.0, "21:9": 21 / 9}
RATIO_TOLERANCE = 0.01
GRID = 3
DIFF_GAIN = 4
# A pixel counts as "changed" when its luma moves by CHANGE_LEVEL or more (0-255). A cell is flagged
# when CHANGE_ALERT_PCT of its pixels changed: a mean over the cell would hide a slightly bigger cup.
CHANGE_LEVEL = 24
CHANGE_ALERT_PCT = 0.5
THUMB_WIDTH = 480
FONTS = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def new_path(path: Path) -> Path:
    if path.exists():
        fail(f"{path} already exists; refusing to overwrite (save a new version instead)")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def font(size: int) -> ImageFont.ImageFont:
    for candidate in FONTS:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size)


def floats(text: str, count: int) -> list[float]:
    values = [float(v) for v in text.split(",")]
    if len(values) != count:
        fail(f"expected {count} comma-separated numbers, got {text!r}")
    return values


def nearest_ratio(w: int, h: int) -> tuple[str, float]:
    name = min(RATIOS, key=lambda k: abs(w / h - RATIOS[k]))
    return name, (w / h - RATIOS[name]) / RATIOS[name]


def cmd_info(a: argparse.Namespace) -> int:
    bad = 0
    for path in a.images:
        with Image.open(path) as im:
            w, h = im.size
            name, dev = nearest_ratio(w, h)
            ok = abs(dev) <= RATIO_TOLERANCE
            bad += not ok
            print(f"{'OK ' if ok else 'OFF'} {path}: {w}x{h} {im.mode} nearest {name} ({dev:+.2%})")
    return 1 if bad else 0


def crop_to_ratio(im: Image.Image, ratio: float, anchor: list[float]) -> Image.Image:
    w, h = im.size
    cw, ch = (round(h * ratio), h) if w / h > ratio else (w, round(w / ratio))
    x = round((w - cw) * min(max(anchor[0], 0), 1))
    y = round((h - ch) * min(max(anchor[1], 0), 1))
    return im.crop((x, y, x + cw, y + ch))


def cmd_fit(a: argparse.Namespace) -> int:
    out = new_path(Path(a.out))
    with Image.open(a.image) as im:
        res = crop_to_ratio(im, RATIOS.get(a.ratio) or eval_ratio(a.ratio), floats(a.anchor, 2))
        if a.size:
            res = res.resize(tuple(int(v) for v in a.size.lower().split("x")), Image.LANCZOS)
        res.save(out)
        print(f"{out}: {im.size[0]}x{im.size[1]} -> {res.size[0]}x{res.size[1]}")
    return 0


def eval_ratio(text: str) -> float:
    w, h = (float(v) for v in text.split(":"))
    return w / h


def cmd_zoom(a: argparse.Namespace) -> int:
    out = new_path(Path(a.out))
    cx, cy = floats(a.center, 2)
    with Image.open(a.image) as im:
        w, h = im.size
        cw, ch = w / a.factor, h / a.factor
        x0 = min(max(cx * w - cw / 2, 0), w - cw)
        y0 = min(max(cy * h - ch / 2, 0), h - ch)
        im.crop((round(x0), round(y0), round(x0 + cw), round(y0 + ch))).resize((w, h), Image.LANCZOS).save(out)
    print(f"{out}: {a.factor}x push-in at ({cx:.2f},{cy:.2f})")
    return 0


def cmd_patch(a: argparse.Namespace) -> int:
    out = new_path(Path(a.out))
    with Image.open(a.original) as orig, Image.open(a.edited) as edited:
        base = orig.convert("RGB")
        top = edited.convert("RGB").resize(base.size, Image.LANCZOS)
        x, y, bw, bh = floats(a.box, 4)
        if max(x, y, bw, bh) <= 1:  # fractions of the frame
            x, y, bw, bh = x * base.width, y * base.height, bw * base.width, bh * base.height
        mask = Image.new("L", base.size, 0)
        ImageDraw.Draw(mask).rectangle((x, y, x + bw, y + bh), fill=255)
        if a.feather:
            mask = mask.filter(ImageFilter.GaussianBlur(a.feather))
        Image.composite(top, base, mask).save(out)
    print(f"{out}: pasted box {round(x)},{round(y)},{round(bw)}x{round(bh)} from {a.edited}")
    return 0


def luma(im: Image.Image) -> float:
    return ImageStat.Stat(im.convert("L")).mean[0]


def pct(mask: Image.Image) -> float:
    """Percent of white pixels in a 0/255 mask."""
    return ImageStat.Stat(mask).mean[0] / 255 * 100


def cmd_pair(a: argparse.Namespace) -> int:
    out_dir = Path(a.out_dir)
    with Image.open(a.first) as first_im, Image.open(a.last) as last_im:
        first, last = first_im.convert("RGB"), last_im.convert("RGB")
    if first.size != last.size:
        print(f"SIZE MISMATCH: first {first.size} vs last {last.size} (fix before submitting)")
        last = last.resize(first.size, Image.LANCZOS)
    Image.blend(first, last, 0.5).save(new_path(out_dir / "overlay.png"))
    diff = ImageChops.difference(first, last).convert("L")
    diff.point(lambda v: min(255, v * DIFF_GAIN)).save(new_path(out_dir / "diff.png"))
    changed = diff.point(lambda v: 255 if v >= CHANGE_LEVEL else 0)
    fm, lm = ImageStat.Stat(first).mean, ImageStat.Stat(last).mean
    print(
        f"mean RGB first {[round(v, 1) for v in fm]} last {[round(v, 1) for v in lm]} | "
        f"luma {luma(first):.1f} -> {luma(last):.1f} | changed pixels {pct(changed):.2f}%"
    )
    w, h = first.size
    print(f"changed pixels per cell, {GRID}x{GRID} grid ('!' = {CHANGE_ALERT_PCT}% or more moved by {CHANGE_LEVEL}+):")
    for row in range(GRID):
        cells = []
        for col in range(GRID):
            box = (col * w // GRID, row * h // GRID, (col + 1) * w // GRID, (row + 1) * h // GRID)
            value = pct(changed.crop(box))
            cells.append(f"{value:6.2f}%{'!' if value >= CHANGE_ALERT_PCT else ' '}")
        print("  " + " ".join(cells))
    print(f"wrote {out_dir / 'overlay.png'} and {out_dir / 'diff.png'}. Areas that must not change should be dark.")
    return 0


def cmd_gray(a: argparse.Namespace) -> int:
    for path in map(Path, a.images):
        with Image.open(path) as im:
            out = new_path(Path(a.out_dir) / f"{path.stem}_gray.png")
            im.convert("L").save(out)
            print(out)
    return 0


def cmd_phone(a: argparse.Namespace) -> int:
    out = new_path(Path(a.out))
    with Image.open(a.image) as im:
        im.resize((a.width, round(im.height * a.width / im.width)), Image.LANCZOS).save(out)
    print(f"{out}: {a.width}px wide. Can you still read every face and prop?")
    return 0


def draw_guides(draw: ImageDraw.ImageDraw, w: int, h: int, color: str = "#ff3b3b", width: int = 3) -> None:
    for frac in GUIDES:
        draw.line((frac * w, 0, frac * w, h), fill=color, width=width)
        draw.line((0, frac * h, w, frac * h), fill=color, width=max(1, width // 2))


def cmd_guides(a: argparse.Namespace) -> int:
    out = new_path(Path(a.out))
    with Image.open(a.image) as im:
        canvas = im.convert("RGB")
        draw_guides(ImageDraw.Draw(canvas), *canvas.size)
        canvas.save(out)
    print(f"{out}: heads/eyes should sit near a vertical line, not the centre")
    return 0


def contact_sheet(paths: list[Path], cols: int, thumb_w: int = THUMB_WIDTH) -> Image.Image:
    thumbs = []
    for path in paths:
        with Image.open(path) as im:
            thumbs.append((path.name, im.convert("RGB").resize((thumb_w, round(im.height * thumb_w / im.width)))))
    label_h, pad = 28, 8
    cell_h = max(t.height for _, t in thumbs) + label_h
    rows = -(-len(thumbs) // cols)
    sheet = Image.new("RGB", (cols * (thumb_w + pad) + pad, rows * (cell_h + pad) + pad), "#202020")
    draw, fnt = ImageDraw.Draw(sheet), font(18)
    for i, (name, thumb) in enumerate(thumbs):
        x, y = pad + (i % cols) * (thumb_w + pad), pad + (i // cols) * (cell_h + pad)
        sheet.paste(thumb, (x, y + label_h))
        draw.text((x + 4, y + 4), name, fill="#f0f0f0", font=fnt)
    return sheet


def cmd_sheet(a: argparse.Namespace) -> int:
    out = new_path(Path(a.out))
    contact_sheet([Path(p) for p in a.images], a.cols).save(out)
    print(out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("info")
    s.add_argument("images", nargs="+")
    s = sub.add_parser("fit")
    s.add_argument("image")
    s.add_argument("--ratio", required=True)
    s.add_argument("--size")
    s.add_argument("--anchor", default="0.5,0.5")
    s.add_argument("--out", required=True)
    s = sub.add_parser("zoom")
    s.add_argument("image")
    s.add_argument("--factor", type=float, required=True)
    s.add_argument("--center", default="0.5,0.5")
    s.add_argument("--out", required=True)
    s = sub.add_parser("patch")
    s.add_argument("original")
    s.add_argument("edited")
    s.add_argument("--box", required=True, help="x,y,w,h in px or as 0-1 fractions")
    s.add_argument("--feather", type=float, default=12.0)
    s.add_argument("--out", required=True)
    s = sub.add_parser("pair")
    s.add_argument("first")
    s.add_argument("last")
    s.add_argument("--out-dir", required=True)
    s = sub.add_parser("gray")
    s.add_argument("images", nargs="+")
    s.add_argument("--out-dir", required=True)
    s = sub.add_parser("phone")
    s.add_argument("image")
    s.add_argument("--width", type=int, default=390)
    s.add_argument("--out", required=True)
    s = sub.add_parser("guides")
    s.add_argument("image")
    s.add_argument("--out", required=True)
    s = sub.add_parser("sheet")
    s.add_argument("images", nargs="+")
    s.add_argument("--out", required=True)
    s.add_argument("--cols", type=int, default=4)
    return p


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = build_parser().parse_args()
    return globals()[f"cmd_{a.cmd}"](a)


if __name__ == "__main__":
    sys.exit(main())
