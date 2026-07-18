"""
DISABLED: junction-sphere unit-cell seed export.

Use paper_box seeds instead:
  py -3 scripts/export_unitcell_paper_box_cut.py --Q 0 0.5 1.0 1.5
  # Q=1 OCP: bash scripts/linux/run_ocp_glue_fuse_pilot.sh
"""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "export_unitcell_seed_check.py is disabled: junction-sphere seeds are no longer "
        "supported.\n"
        "Use paper_box instead:\n"
        "  py -3 scripts/export_unitcell_paper_box_cut.py --Q 0 0.5 1.0 1.5\n"
        "  # Q=1 OCP: bash scripts/linux/run_ocp_glue_fuse_pilot.sh",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
