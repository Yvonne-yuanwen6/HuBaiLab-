from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape
from src.export.ocp_unitcell_fuse import ocp_mass, ocp_shape_topology


def _stat(label: str, path: str) -> None:
    if not os.path.isfile(path):
        print(f"{label}: MISSING")
        return
    shape = ocp_read_step_shape(path)
    topo = ocp_shape_topology(shape, check_brep=True)
    print(
        f"{label}: faces={topo.get('faces')} valid={topo.get('brep_valid')} "
        f"mass={ocp_mass(shape):.2f} size={os.path.getsize(path)}"
    )


def main() -> None:
    root = os.path.join("output", "cad", "_exp_node_transition", "_hard_cad_delivery")
    _stat(
        "delivery Q1 n12 r0.15",
        os.path.join(root, "exp_hardSwFillet_af2q1p0_L20_d2p0_r0p15_n12_1x1.step"),
    )
    _stat(
        "main Q1 n21 r0.12",
        os.path.join(
            root,
            "_sw_main_chain_r0p12",
            "exp_planeChain_af2q1p0_L20_d2p0_1x1_main_r0p12_n21.step",
        ),
    )
    _stat(
        "delivery Q1.5 n11 r0.15",
        os.path.join(root, "exp_hardSwFillet_af2q1p5_L20_d2p0_r0p15_n11_1x1.step"),
    )
    _stat(
        "main Q1.5 n9 r0.12",
        os.path.join(
            root,
            "_sw_main_chain_r0p12",
            "exp_planeChain_af2q1p5_L20_d2p0_1x1_main_r0p12_n9.step",
        ),
    )


if __name__ == "__main__":
    main()
