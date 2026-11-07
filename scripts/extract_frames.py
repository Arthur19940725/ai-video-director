#!/usr/bin/env python3
"""Extract frames from a video with ffmpeg, for checking clips and cut points. Never overwrites a file.

extract_frames.py VIDEO --out-dir DIR --first-last          first.png, last.png (colour drift, end jumps)
extract_frames.py VIDEO --out-dir DIR --every 0.5           one frame every 0.5 s (reference films)
extract_frames.py VIDEO --out-dir DIR --at 1.2,3.4          frames at given times
extract_frames.py VIDEO --out-dir DIR --around 4.7,9.4 --n 3  frames k-n..k+n around each cut
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # works under `python -I` too

from frame_tools import fail, floats, new_path  # noqa: E402


def ffmpeg(*args: str) -> None:
    exe = shutil.which("ffmpeg")
    if not exe:
        fail("ffmpeg not found")
    run = subprocess.run([exe, "-v", "error", "-y", *args], capture_output=True, text=True)
    if run.returncode:
        fail(f"ffmpeg failed: {run.stderr.strip()[-800:]}")


def video_fps(video: str) -> float:
    exe = shutil.which("ffprobe")
    if not exe:
        fail("ffprobe not found")
    run = subprocess.run(
        [exe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "json", video],
        capture_output=True,
        text=True,
        check=True,
    )
    num, den = json.loads(run.stdout)["streams"][0]["r_frame_rate"].split("/")
    return float(num) / float(den)


def cmd_extract(a: argparse.Namespace) -> int:
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if a.first_last:
        first, last = new_path(out_dir / "first.png"), new_path(out_dir / "last.png")
        ffmpeg("-i", a.video, "-frames:v", "1", str(first))
        ffmpeg("-sseof", "-1", "-i", a.video, "-update", "1", str(last))
        print(f"{first}\n{last}")
    elif a.every:
        if any(out_dir.glob("every_*.png")):
            fail(f"{out_dir} already has every_*.png; use a new folder")
        ffmpeg("-i", a.video, "-vf", f"fps=1/{a.every}", str(out_dir / "every_%04d.png"))
        print(f"{len(list(out_dir.glob('every_*.png')))} frames in {out_dir}")
    elif a.at:
        for t in floats(a.at, len(a.at.split(","))):
            out = new_path(out_dir / f"at_{t:07.3f}s.png")
            ffmpeg("-ss", str(t), "-i", a.video, "-frames:v", "1", str(out))
            print(out)
    elif a.around:
        fps = video_fps(a.video)
        for t in floats(a.around, len(a.around.split(","))):
            k = round(t * fps)
            k0, k1 = max(k - a.n, 0), k + a.n
            tmp = out_dir / f"_tmp_{t:07.3f}"
            tmp.mkdir(exist_ok=False)
            ffmpeg(
                "-i",
                a.video,
                "-vf",
                f"select='between(n\\,{k0}\\,{k1})'",
                "-fps_mode",
                "passthrough",
                str(tmp / "%03d.png"),
            )
            for i, frame in enumerate(sorted(tmp.glob("*.png"))):
                frame.rename(new_path(out_dir / f"cut_{t:07.3f}s_f{k0 + i:05d}.png"))
            tmp.rmdir()
            print(f"cut at {t}s (frame {k} @ {fps:.3f} fps): frames {k0}-{k1}")
    else:
        fail("choose one of --first-last, --every, --at, --around")
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--first-last", action="store_true")
    p.add_argument("--every", type=float, help="seconds between frames")
    p.add_argument("--at", help="comma-separated times in seconds")
    p.add_argument("--around", help="comma-separated cut times in seconds")
    p.add_argument("--n", type=int, default=3, help="frames before and after each cut")
    return cmd_extract(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())
