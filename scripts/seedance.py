#!/usr/bin/env python3
"""Seedance (Volcengine Ark) first/last-frame image-to-video client.

Spending is gated in code, not only in prose:
  * submit needs a project budget (``budget --set``);
  * submit without --yes prints the quote and does NOT submit;
  * submit refuses when spent + quote would exceed the budget (exit 5);
  * billing or quota errors stop with exit 3 and are never retried;
  * POST is never retried, so a network error cannot double-submit.
The API key comes from ARK_API_KEY and is never printed or written to disk.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # works under `python -I` too

from seedance_lib import (  # noqa: E402
    DONE_STATUSES,
    EXIT_BUDGET,
    EXIT_FAIL,
    TASKS_PATH,
    StopError,
    api,
    append_ledger,
    download,
    image_data_url,
    now,
    price_per_sec,
    read_budget,
    read_ledger,
    sha256,
    spent_cny,
    task_file,
)


# ---------- commands ----------
def cmd_budget(a: argparse.Namespace) -> int:
    project = Path(a.project)
    if a.set is not None:
        project.mkdir(parents=True, exist_ok=True)
        (project / "budget.json").write_text(json.dumps({"total_cny": a.set, "set_at": now()}), encoding="utf-8")
        append_ledger(project, {"event": "budget", "time": now(), "total_cny": a.set})
    total, spent = read_budget(project), spent_cny(read_ledger(project))
    print(f"budget ¥{total:.2f} | spent (est.) ¥{spent:.2f} | remaining ¥{total - spent:.2f}")
    return 0


def print_quote(model: str, seconds: int, resolution: str, unit: float, project: Path | None) -> float:
    est = round(unit * seconds, 2)
    print(f"QUOTE {model} {resolution} {seconds}s x ¥{unit:.3f}/s = ¥{est:.2f} (estimate; the Ark bill wins)")
    if project is not None:
        total, spent = read_budget(project), spent_cny(read_ledger(project))
        flag = "  OVER BUDGET" if spent + est > total else ""
        print(
            f"budget ¥{total:.2f} | spent ¥{spent:.2f} | after this ¥{spent + est:.2f} | "
            f"remaining ¥{total - spent - est:.2f}{flag}"
        )
    return est


def cmd_quote(a: argparse.Namespace) -> int:
    unit = price_per_sec(a.model, a.resolution, a.price_per_sec)
    print_quote(a.model, a.duration * a.count, a.resolution, unit, Path(a.project) if a.project else None)
    return 0


def cmd_submit(a: argparse.Namespace) -> int:
    project, out = Path(a.project), Path(a.out)
    if out.exists() or task_file(out).exists():
        raise StopError(f"{out} already exists. Save new versions as new files (_v2, _v3).")
    prompt = Path(a.prompt_file).read_text(encoding="utf-8").strip()
    if not prompt:
        raise StopError("The prompt file is empty")
    content: list[dict] = [{"type": "text", "text": prompt}]
    frames = [("first_frame", Path(a.first))] + ([("last_frame", Path(a.last))] if a.last else [])
    images_meta, sizes = [], []
    for role, path in frames:
        url, size = image_data_url(path, a.ratio)
        content.append({"type": "image_url", "image_url": {"url": url}, "role": role})
        images_meta.append({"role": role, "path": str(path.resolve()), "sha256": sha256(path), "size": size})
        sizes.append(size)
    if len(sizes) == 2 and None not in sizes and sizes[0] != sizes[1] and not a.allow_size_mismatch:
        raise StopError(f"First frame {sizes[0]} and last frame {sizes[1]} differ. Make them the same size first.")
    params = {
        "model": a.model,
        "resolution": a.resolution,
        "ratio": a.ratio,
        "duration": a.duration,
        "generate_audio": not a.no_audio,
        "watermark": False,
    }
    if a.return_last_frame:
        params["return_last_frame"] = True
    if a.extra:
        params.update(json.loads(a.extra))
    unit = price_per_sec(a.model, a.resolution, a.price_per_sec)
    est = print_quote(a.model, a.duration, a.resolution, unit, project)
    if not a.yes:
        print("NOT SUBMITTED. Re-run with --yes only after the reviewer wrote 通过 and the user approved this quote.")
        return 0
    if spent_cny(read_ledger(project)) + est > read_budget(project):
        raise StopError("Over budget: not submitted. Ask the user before raising the budget.", EXIT_BUDGET)
    task_id = api("POST", TASKS_PATH, {**params, "content": content})["id"]
    out.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "task_id": task_id,
        "created": now(),
        "params": params,
        "prompt": prompt,
        "images": images_meta,
        "est_cny": est,
        "project": str(project.resolve()),
        "out": str(out.resolve()),
    }
    task_file(out).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    append_ledger(
        project,
        {
            "event": "submitted",
            "time": now(),
            "task_id": task_id,
            "shot": a.shot or out.stem,
            "out": str(out),
            "model": a.model,
            "duration": a.duration,
            "resolution": a.resolution,
            "est_cny": est,
        },
    )
    print(f"SUBMITTED {task_id}")
    return wait_for(project, task_id, out, a.interval, a.timeout) if a.wait else 0


def wait_for(project: Path, task_id: str, out: Path, interval: float, timeout: float) -> int:
    deadline, last = time.monotonic() + timeout, None
    while True:
        task = api("GET", f"{TASKS_PATH}/{task_id}")
        status = task.get("status")
        if status != last:
            print(f"[{now()}] {task_id}: {status}", flush=True)
            last = status
        if status in DONE_STATUSES:
            break
        if time.monotonic() > deadline:
            print(f"Timed out; the task keeps running. Resume: wait --project {project} {task_id}")
            return EXIT_FAIL
        time.sleep(interval)
    entry = {
        "event": "finished",
        "time": now(),
        "task_id": task_id,
        "status": status,
        "tokens": (task.get("usage") or {}).get("completion_tokens"),
    }
    if status == "succeeded":
        result = task.get("content") or {}
        if not result.get("video_url"):
            raise StopError(f"Task succeeded but has no video_url: {json.dumps(task, ensure_ascii=False)}")
        out.parent.mkdir(parents=True, exist_ok=True)
        download(result["video_url"], out)
        if result.get("last_frame_url"):
            download(result["last_frame_url"], out.with_name(out.stem + "_lastframe.jpg"))
        entry["out"] = str(out)
    record_path = task_file(out)
    record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else {"task_id": task_id}
    record["result"] = task
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    append_ledger(project, entry)
    if status != "succeeded":
        print(f"FAILED {task_id}: {status} {json.dumps(task.get('error'), ensure_ascii=False)}")
        return EXIT_FAIL
    print(f"DOWNLOADED {out}")
    return 0


def cmd_wait(a: argparse.Namespace) -> int:
    project = Path(a.project)
    out = (
        Path(a.out)
        if a.out
        else next(
            (
                Path(e["out"])
                for e in read_ledger(project)
                if e.get("event") == "submitted" and e["task_id"] == a.task_id
            ),
            None,
        )
    )
    if out is None:
        raise StopError(f"Task {a.task_id} is not in {project}/ledger.jsonl; pass --out")
    return wait_for(project, a.task_id, out, a.interval, a.timeout)


def cmd_status(a: argparse.Namespace) -> int:
    print(json.dumps(api("GET", f"{TASKS_PATH}/{a.task_id}"), ensure_ascii=False, indent=2))
    return 0


def cmd_ledger(a: argparse.Namespace) -> int:
    entries = read_ledger(Path(a.project))
    finished = {e["task_id"]: e for e in entries if e.get("event") == "finished"}
    for e in (e for e in entries if e.get("event") == "submitted"):
        status = finished.get(e["task_id"], {}).get("status", "pending")
        print(f"{e['time']} {e['shot']:<10} {e['model']} {e['duration']}s ¥{e['est_cny']:.2f} {status} {e['out']}")
    return cmd_budget(argparse.Namespace(project=a.project, set=None))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("budget", help="show or set the project budget (CNY)")
    b.add_argument("--project", required=True)
    b.add_argument("--set", type=float)
    q = sub.add_parser("quote", help="estimate cost without submitting")
    s = sub.add_parser("submit", help="quote; with --yes submit a first/last-frame task")
    for sp in (q, s):
        sp.add_argument("--model", required=True)
        sp.add_argument("--duration", type=int, required=True, help="seconds (2.0: 4-15, 2.5: 4-30)")
        sp.add_argument("--resolution", default="720p")
        sp.add_argument("--price-per-sec", type=float, help="override the CNY/second estimate")
    q.add_argument("--count", type=int, default=1, help="number of clips")
    q.add_argument("--project")
    s.add_argument("--project", required=True)
    s.add_argument("--prompt-file", required=True)
    s.add_argument("--first", required=True, help="first frame image")
    s.add_argument("--last", help="last frame image")
    s.add_argument("--out", required=True, help="video path to create, e.g. clips/S01_v1.mp4")
    s.add_argument("--shot")
    s.add_argument("--ratio", required=True, help="16:9, 9:16, 4:3, 3:4, 1:1, 21:9 or adaptive")
    s.add_argument("--no-audio", action="store_true")
    s.add_argument("--return-last-frame", action="store_true")
    s.add_argument("--allow-size-mismatch", action="store_true")
    s.add_argument("--extra", help="JSON object merged into the request parameters")
    s.add_argument("--yes", action="store_true", help="really submit (only after the user approved the quote)")
    s.add_argument("--wait", action="store_true")
    w = sub.add_parser("wait", help="poll a task and download the result")
    w.add_argument("task_id")
    w.add_argument("--project", required=True)
    w.add_argument("--out")
    for sp in (s, w):
        sp.add_argument("--interval", type=float, default=10.0)
        sp.add_argument("--timeout", type=float, default=1800.0)
    st = sub.add_parser("status", help="print the raw task status")
    st.add_argument("task_id")
    lg = sub.add_parser("ledger", help="list submissions and spending")
    lg.add_argument("--project", required=True)
    return p


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = build_parser().parse_args()
    handlers = {
        "budget": cmd_budget,
        "quote": cmd_quote,
        "submit": cmd_submit,
        "wait": cmd_wait,
        "status": cmd_status,
        "ledger": cmd_ledger,
    }
    try:
        return handlers[a.cmd](a)
    except StopError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
