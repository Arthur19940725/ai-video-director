#!/usr/bin/env python3
"""Library for seedance.py: pricing, budget ledger, image checks and the Ark HTTP client.

Spending is gated in code, not only in prose:
  * submit needs a project budget (``budget --set``);
  * submit without --yes prints the quote and does NOT submit;
  * submit refuses when spent + quote would exceed the budget (exit 5);
  * billing or quota errors stop with exit 3 and are never retried;
  * POST is never retried, so a network error cannot double-submit.
The API key comes from ARK_API_KEY and is never printed or written to disk.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
TASKS_PATH = "/contents/generations/tasks"
# Estimated CNY per generated second at 720p (Eian's article, 2026-11). The Ark bill wins.
PRICE_720P_CNY = {"doubao-seedance-2-5": 1.5, "doubao-seedance-2-0-mini": 0.5}
PIXELS = {"480p": 854 * 480, "720p": 1280 * 720, "1080p": 1920 * 1080, "4k": 3840 * 2160}
RATIOS = {"16:9": 16 / 9, "4:3": 4 / 3, "1:1": 1.0, "3:4": 3 / 4, "9:16": 9 / 16, "21:9": 21 / 9}
RATIO_TOLERANCE = 0.01
MAX_IMAGE_BYTES = 30 * 1024 * 1024
MAX_BODY_BYTES = 64 * 1024 * 1024
MIN_SIDE, MAX_SIDE, MIN_ASPECT, MAX_ASPECT = 300, 6000, 0.4, 2.5
IMAGE_FORMATS = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".webp": "webp",
    ".bmp": "bmp",
    ".tif": "tiff",
    ".tiff": "tiff",
    ".gif": "gif",
    ".heic": "heic",
    ".heif": "heif",
}
BILLING_MARKERS = ("overdue", "arrear", "insufficient", "balance", "quotaexceeded", "setlimitexceeded", "欠费", "余额")
DONE_STATUSES = {"succeeded", "failed", "expired", "cancelled"}
UNBILLED_STATUSES = {"failed", "expired", "cancelled"}
RETRY_HTTP_CODES = {429, 500, 502, 503, 504}
HTTP_TIMEOUT_S, GET_RETRIES = 120, 5
EXIT_FAIL, EXIT_BILLING, EXIT_NO_KEY, EXIT_BUDGET = 1, 3, 4, 5


class StopError(Exception):
    """A failure that must end the run with a specific exit code."""

    def __init__(self, message: str, code: int = EXIT_FAIL) -> None:
        super().__init__(message)
        self.code = code


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- pricing, budget, ledger ----------
def price_per_sec(model: str, resolution: str, override: float | None) -> float:
    if override is not None:
        return override
    matches = [prefix for prefix in PRICE_720P_CNY if model.startswith(prefix)]
    if not matches:
        raise StopError(f"No known price for model {model!r}. Pass --price-per-sec <CNY per second>.")
    if resolution not in PIXELS:
        raise StopError(f"Unknown resolution {resolution!r}. Pass --price-per-sec.")
    base = PRICE_720P_CNY[max(matches, key=len)]
    return base * PIXELS[resolution] / PIXELS["720p"]


def read_budget(project: Path) -> float:
    path = project / "budget.json"
    if not path.exists():
        raise StopError(
            f"No budget for {project}. Ask the user, then run: budget --project {project} --set <CNY>", EXIT_BUDGET
        )
    return float(json.loads(path.read_text(encoding="utf-8"))["total_cny"])


def read_ledger(project: Path) -> list[dict]:
    path = project / "ledger.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_ledger(project: Path, entry: dict) -> None:
    with (project / "ledger.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def spent_cny(entries: list[dict]) -> float:
    unbilled = {e["task_id"] for e in entries if e.get("event") == "finished" and e.get("status") in UNBILLED_STATUSES}
    return round(
        sum(e["est_cny"] for e in entries if e.get("event") == "submitted" and e["task_id"] not in unbilled), 2
    )


# ---------- images ----------
def image_size(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image
    except ImportError:
        print("WARNING: Pillow is missing, image size checks skipped", file=sys.stderr)
        return None
    with Image.open(path) as im:
        return im.size


def image_data_url(path: Path, ratio: str) -> tuple[str, tuple[int, int] | None]:
    if not path.is_file():
        raise StopError(f"Image not found: {path}")
    fmt = IMAGE_FORMATS.get(path.suffix.lower())
    if fmt is None:
        raise StopError(f"Unsupported image format: {path.suffix}")
    raw = path.read_bytes()
    if len(raw) >= MAX_IMAGE_BYTES:
        raise StopError(f"{path} is {len(raw)} bytes; the limit is 30 MB")
    size = image_size(path)
    if size:
        w, h = size
        if not (MIN_SIDE <= w <= MAX_SIDE and MIN_SIDE <= h <= MAX_SIDE and MIN_ASPECT <= w / h <= MAX_ASPECT):
            raise StopError(f"{path} is {w}x{h}; Seedance needs sides of 300-6000 px and w/h of 0.4-2.5")
        if ratio in RATIOS and abs(w / h - RATIOS[ratio]) / RATIOS[ratio] > RATIO_TOLERANCE:
            raise StopError(f"{path} is {w}x{h}, not {ratio}. Crop it first: frame_tools.py fit --ratio {ratio}")
    return f"data:image/{fmt};base64," + base64.b64encode(raw).decode("ascii"), size


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------- HTTP ----------
def api(method: str, path: str, body: dict | None = None) -> dict:
    key = os.environ.get("ARK_API_KEY")
    if not key:
        raise StopError(
            "ARK_API_KEY is not set. The user must set it as an environment variable "
            "(never paste it into the chat), then restart the terminal.",
            EXIT_NO_KEY,
        )
    data = json.dumps(body).encode("utf-8") if body is not None else None
    if data is not None and len(data) >= MAX_BODY_BYTES:
        raise StopError("Request body is 64 MB or more; use smaller images")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    retries = GET_RETRIES if method == "GET" else 1
    for attempt in range(retries):
        req = urllib.request.Request(BASE_URL + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            if any(marker in detail.lower() for marker in BILLING_MARKERS):
                raise StopError(
                    f"Billing/quota stop (HTTP {exc.code}): {detail}\n"
                    "Do not top up or buy quota. Rough-cut the clips you have and show the user.",
                    EXIT_BILLING,
                ) from exc
            if exc.code in RETRY_HTTP_CODES and attempt < retries - 1:
                time.sleep(2**attempt)
                continue
            raise StopError(f"HTTP {exc.code} from Ark: {detail}") from exc
        except urllib.error.URLError as exc:
            if attempt < retries - 1:
                time.sleep(2**attempt)
                continue
            hint = (
                " The task may still have been created: check the Ark console before resubmitting."
                if method == "POST"
                else ""
            )
            raise StopError(f"Network error: {exc.reason}.{hint}") from exc
    raise StopError("retries exhausted")


def download(url: str, dest: Path) -> None:
    if dest.exists():
        raise StopError(f"{dest} already exists; refusing to overwrite")
    part = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_S) as resp, part.open("wb") as fh:
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
    part.rename(dest)


def task_file(out: Path) -> Path:
    return out.with_name(out.name + ".task.json")
