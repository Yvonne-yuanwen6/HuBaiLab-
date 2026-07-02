#!/usr/bin/env python3
"""Strip CRLF from linux shell scripts (Windows sync artifact)."""
from __future__ import annotations

import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATTERN = os.path.join(ROOT, "scripts", "linux", "*.sh")


def main() -> int:
    n = 0
    for path in sorted(glob.glob(PATTERN)):
        raw = open(path, "rb").read()
        if b"\r" not in raw:
            continue
        open(path, "wb").write(raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
        print(f"fixed: {path}")
        n += 1
    print(f"done: {n} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
