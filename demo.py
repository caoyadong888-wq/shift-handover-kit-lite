#!/usr/bin/env python3
"""Run the lite generator on the synthetic night shift. Exit 0 when the markdown lands."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main() -> int:
    py = sys.executable
    cmd = [
        py,
        "scripts/handover_gen.py",
        "--input",
        "samples/shift_input.json",
        "--tickets",
        "samples/tickets.csv",
        "--out",
        "out",
        "--lang",
        "both",
    ]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    display = " ".join(["python3", *cmd[1:]])
    print("Shift handover kit lite demo", flush=True)
    print(flush=True)
    print("$ " + display, flush=True)
    completed = subprocess.run(cmd, cwd=ROOT, env=env)
    if completed.returncode not in (0, 2, 3):
        print(f"demo failed: exit {completed.returncode}", flush=True)
        return completed.returncode or 1
    markdown = ROOT / "out" / "handover.md"
    if not markdown.is_file():
        print("missing out/handover.md", flush=True)
        return 1
    for name in ("handover.html", "handover.json"):
        if (ROOT / "out" / name).is_file():
            print(f"lite wrote out/{name}", flush=True)
            return 1
    print(f"wrote out/handover.md ({markdown.stat().st_size} bytes)", flush=True)
    print(f"generator exit {completed.returncode}", flush=True)
    print("demo complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
