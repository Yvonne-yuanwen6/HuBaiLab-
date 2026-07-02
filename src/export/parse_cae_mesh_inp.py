"""Parse lattice nodes/elements from an Abaqus/CAE writeInput mesh-only INP."""

from __future__ import annotations

import os
import re


def parse_cae_mesh_inp(
    path: str,
    *,
    part_name: str | None = None,
    element_type: str = "C3D4",
) -> tuple[list[tuple[int, float, float, float]], list[tuple[int, ...]]]:
    """
    Read *Node and *Element blocks from a CAE-exported INP Part section.

    Returns (mesh_nodes, mesh_elements) where mesh_nodes are (nid, x, y, z)
    and mesh_elements are (eid, n1, ...) for linear (C3D4) or quadratic (C3D10M) tets.
    """
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)

    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()

    part_re = re.compile(r"^\*Part,\s*name=([^,\s]+)", re.I)
    target_part = part_name
    in_part = part_name is None
    section: str | None = None
    nodes: list[tuple[int, float, float, float]] = []
    elements: list[tuple[int, ...]] = []
    elem_type_upper = element_type.upper()
    min_elem_nodes = 10 if elem_type_upper in ("C3D10M", "C3D10") else 4

    def _flush_section() -> None:
        nonlocal section
        section = None

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("**"):
            continue

        m_part = part_re.match(line)
        if m_part:
            name = m_part.group(1)
            in_part = target_part is None or name == target_part
            if target_part is None:
                target_part = name
            _flush_section()
            continue

        if not in_part:
            continue

        upper = line.upper()
        if upper.startswith("*END PART"):
            break
        if upper.startswith("*NODE"):
            section = "node"
            continue
        if upper.startswith("*ELEMENT"):
            if elem_type_upper not in upper:
                raise ValueError(f"Expected *Element, type={element_type} in {path}, got: {line}")
            section = "element"
            continue
        if line.startswith("*"):
            _flush_section()
            continue

        if section == "node":
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 4:
                continue
            nid = int(parts[0])
            x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
            nodes.append((nid, x, y, z))
        elif section == "element":
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 1 + min_elem_nodes:
                continue
            eid = int(parts[0])
            nids = tuple(int(p) for p in parts[1 : 1 + min_elem_nodes])
            elements.append((eid, *nids))

    if not nodes or not elements:
        raise RuntimeError(
            f"No mesh parsed from {path} (part={target_part!r}, "
            f"nodes={len(nodes)}, elements={len(elements)})"
        )
    return nodes, elements


def count_cae_mesh_inp(
    path: str,
    *,
    part_name: str | None = None,
) -> tuple[int, int]:
    """Return (n_nodes, n_elements) without retaining full connectivity."""
    nodes, elements = parse_cae_mesh_inp(path, part_name=part_name)
    return len(nodes), len(elements)
