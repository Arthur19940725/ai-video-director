#!/usr/bin/env python3
"""Ask the local Codex CLI to draw exactly ONE image, then copy it into the project.

    codex_image.py --prompt-file prompts/img/S01_last_v1.txt --out frames/S01_last_v1.png \
        [--ref design/girl_v2.png --ref frames/S01_first_v1.png] [--model M]

Runs `codex exec --skip-git-repo-check -s read-only --json -` with the prompt on
stdin. Codex saves images under $CODEX_HOME/generated_images/<thread_id>/; the
thread id comes from the `thread.started` event. The output file is never
overwritten. Exit codes: 0 ok, 1 no image, 3 Codex quota/usage limit reached.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HEADER = "Use your image generation tool to create exactly ONE image. Do not run shell commands."
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
LIMIT_MARKERS = ("usage limit", "rate limit", "hit your limit", "quota", "too many requests")
CLOCK_SLACK_S = 2.0
EXIT_NO_IMAGE, EXIT_LIMIT = 1, 3


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def parse_events(stdout: str) -> tuple[str | None, list[str], list[str]]:
    """Return (thread_id, agent messages, error messages) from `codex exec --json` output."""
    thread_id, messages, errors = None, [], []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind == "thread.started":
            thread_id = event.get("thread_id")
        elif kind == "item.completed":
            item = event.get("item") or {}
            if item.get("type") == "agent_message":
                messages.append(item.get("text", ""))
            elif item.get("type") == "error":
                errors.append(item.get("message", ""))
        elif kind in ("turn.failed", "error"):
            errors.append(json.dumps(event.get("error") or event, ensure_ascii=False))
    return thread_id, messages, errors


def find_image(gen_root: Path, thread_id: str | None, started: float) -> tuple[Path | None, str]:
    """Use the thread's own folder. Only when no thread id was parsed, fall back to the
    newest image written after `started` (another Codex session could own it, so say so)."""
    if thread_id:
        folder = gen_root / thread_id
        found = (
            sorted((p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES), key=lambda p: p.stat().st_mtime)
            if folder.is_dir()
            else []
        )
        if not found:
            return None, f"no image in {folder}"
        note = f"thread folder had {len(found)} images; took the newest" if len(found) > 1 else "thread folder"
        return found[-1], note
    if not gen_root.is_dir():
        return None, "no generated_images folder"
    recent = [
        p
        for p in gen_root.glob("*/*")
        if p.suffix.lower() in IMAGE_SUFFIXES and p.stat().st_mtime >= started - CLOCK_SLACK_S
    ]
    if recent:
        return max(recent, key=lambda p: p.stat().st_mtime), "FALLBACK: newest image after start time"
    return None, "no new image found"


def save_image(src: Path, out: Path) -> tuple[int, int] | None:
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image
    except ImportError:
        if src.suffix.lower() != out.suffix.lower():
            raise SystemExit(f"Pillow is missing, cannot convert {src.suffix} to {out.suffix}")
        shutil.copy2(src, out)
        return None
    with Image.open(src) as im:
        if src.suffix.lower() == out.suffix.lower():
            shutil.copy2(src, out)
        else:
            im.convert("RGB" if out.suffix.lower() in (".jpg", ".jpeg") else im.mode).save(out)
        return im.size


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--prompt-file", required=True)
    p.add_argument("--out", required=True, help="image path to create (.png/.jpg/.webp)")
    p.add_argument("--ref", action="append", default=[], help="reference image; repeat for several")
    p.add_argument("--model", help="Codex model override")
    p.add_argument("--timeout", type=float, default=900.0)
    a = p.parse_args()

    out = Path(a.out)
    if out.exists():
        print(f"ERROR: {out} already exists. Save new versions as new files (_v2, _v3).", file=sys.stderr)
        return EXIT_NO_IMAGE
    if out.suffix.lower() not in IMAGE_SUFFIXES:
        print(f"ERROR: --out must end with one of {sorted(IMAGE_SUFFIXES)}", file=sys.stderr)
        return EXIT_NO_IMAGE
    # Codex does not check --image paths itself: it would start a paid turn without the reference.
    missing = [r for r in a.ref if not Path(r).is_file()]
    if missing:
        print(f"ERROR: reference image not found: {missing}", file=sys.stderr)
        return EXIT_NO_IMAGE
    codex = shutil.which("codex")
    if not codex:
        print("ERROR: codex CLI not found. Use the host's own image tool instead.", file=sys.stderr)
        return EXIT_NO_IMAGE
    body = Path(a.prompt_file).read_text(encoding="utf-8").strip()
    prompt = body if HEADER in body else f"{HEADER}\n\n{body}"

    cmd = [codex, "exec", "--skip-git-repo-check", "-s", "read-only", "--json"]
    if a.model:
        cmd += ["-m", a.model]
    cmd.append("-")  # prompt from stdin; keep it before the variadic --image flags
    for ref in a.ref:
        cmd += ["-i", str(Path(ref).resolve())]
    started = time.time()
    try:
        run = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=a.timeout,
            cwd=str(out.parent.resolve() if out.parent.exists() else Path.cwd()),
        )
    except subprocess.TimeoutExpired:
        print(f"ERROR: codex did not finish within {a.timeout:.0f}s", file=sys.stderr)
        return EXIT_NO_IMAGE

    thread_id, messages, errors = parse_events(run.stdout)
    src, note = find_image(codex_home() / "generated_images", thread_id, started)
    if src is None:
        text = " ".join(errors + messages + [run.stderr]).lower()
        if any(marker in text for marker in LIMIT_MARKERS):
            print("ERROR: Codex usage limit reached. Wait for it to reset; do not buy credits.", file=sys.stderr)
            code = EXIT_LIMIT
        else:
            print(f"ERROR: no image produced ({note}).", file=sys.stderr)
            code = EXIT_NO_IMAGE
        for msg in messages[-1:] + errors[-3:]:
            print(f"codex: {msg[:500]}", file=sys.stderr)
        if run.returncode:
            print(f"codex exit code {run.returncode}: {run.stderr.strip()[-500:]}", file=sys.stderr)
        return code
    size = save_image(src, out)
    print(
        json.dumps(
            {"out": str(out), "size": size, "thread_id": thread_id, "source": str(src), "note": note},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
