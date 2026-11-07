#!/usr/bin/env python3
"""Check the ai-video-director toolchain and report what is missing.

Never prints secret values: for ARK_API_KEY it reports only whether it is set.
Exit code 0 when the required tools are present (python, Pillow, ffmpeg,
ffprobe), 1 otherwise. Codex and ARK_API_KEY are reported but are needed only
for later stages, so they do not fail the check.
"""

import os
import shutil
import subprocess
import sys

VERSION_TIMEOUT_S = 20


def first_line(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=VERSION_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"found but failed to run: {exc}"
    text = (out.stdout or out.stderr).strip()
    return text.splitlines()[0] if text else "found"


def key_in_windows_user_env(name: str) -> bool:
    """True when the key exists in HKCU\\Environment (set, but this process started earlier)."""
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return bool(value)
    except OSError:
        return False


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows: list[tuple[str, bool, bool, str]] = []  # (name, ok, required, detail)
    rows.append(("python", sys.version_info >= (3, 8), True, sys.version.split()[0]))
    try:
        import PIL

        rows.append(("Pillow", True, True, PIL.__version__))
    except ImportError:
        rows.append(("Pillow", False, True, "missing: pip install pillow"))
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        rows.append((tool, bool(path), True, first_line([path, "-version"]) if path else "missing: install ffmpeg"))
    codex = shutil.which("codex")
    rows.append(
        (
            "codex (画师)",
            bool(codex),
            False,
            (
                first_line([codex, "--version"])
                if codex
                else "missing: install Codex CLI, or use the host's own image tool"
            ),
        )
    )
    if os.environ.get("ARK_API_KEY"):
        key_detail, key_ok = "set (value hidden)", True
    elif key_in_windows_user_env("ARK_API_KEY"):
        key_detail, key_ok = "set in Windows user env, but not in this process: restart the terminal/agent", False
    else:
        key_detail, key_ok = "not set: the user must create it in the Volcengine Ark console and set it", False
    rows.append(("ARK_API_KEY (Seedance)", key_ok, False, key_detail))

    for name, ok, required, detail in rows:
        mark = "OK  " if ok else ("FAIL" if required else "TODO")
        print(f"[{mark}] {name}: {detail}")
    missing_required = [name for name, ok, required, _ in rows if required and not ok]
    if missing_required:
        print("Missing required tools: " + ", ".join(missing_required))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
