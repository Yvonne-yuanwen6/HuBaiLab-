"""B31 centerline overlay for lattice topology (visualization in Abaqus)."""

from __future__ import annotations

import numpy as np


def _round_key(pos, decimals: int = 6) -> tuple[float, float, float]:
    return tuple(np.round(np.asarray(pos, dtype=float), decimals))


def map_lattice_nodes_to_mesh(
    lattice_nodes: list,
    mesh_nodes: list[tuple[int, float, float, float]],
    *,
    merge_decimals: int = 6,
) -> dict[int, int]:
    """Map generator node id -> existing mesh node id (by position)."""
    mesh_index: dict[tuple[float, float, float], int] = {}
    for nid, x, y, z in mesh_nodes:
        mesh_index[_round_key((x, y, z), merge_decimals)] = nid

    mapping: dict[int, int] = {}
    next_nid = max((n[0] for n in mesh_nodes), default=0) + 1

    for ln in lattice_nodes:
        lid = int(ln[0])
        key = _round_key((ln[1], ln[2], ln[3]), merge_decimals)
        if key in mesh_index:
            mapping[lid] = mesh_index[key]
        else:
            mapping[lid] = next_nid
            mesh_index[key] = next_nid
            next_nid += 1

    return mapping


def build_wireframe_overlay(
    lattice_nodes: list,
    beams: list,
    mesh_nodes: list[tuple[int, float, float, float]],
    *,
    node_id_start: int,
    elem_id_start: int,
    merge_decimals: int = 6,
) -> tuple[list[tuple[int, float, float, float]], list[tuple[int, int, int]], list[int]]:
    """
    Build B31 centerline elements on lattice topology.

    Returns extra nodes (only positions not already in mesh), B31 elements, element ids.
    """
    mesh_index: dict[tuple[float, float, float], int] = {}
    for nid, x, y, z in mesh_nodes:
        mesh_index[_round_key((x, y, z), merge_decimals)] = nid

    lattice_nid: dict[int, int] = {}
    extra_nodes: list[tuple[int, float, float, float]] = []
    next_nid = node_id_start

    for ln in lattice_nodes:
        lid = int(ln[0])
        pos = (float(ln[1]), float(ln[2]), float(ln[3]))
        key = _round_key(pos, merge_decimals)
        if key in mesh_index:
            lattice_nid[lid] = mesh_index[key]
        else:
            lattice_nid[lid] = next_nid
            mesh_index[key] = next_nid
            extra_nodes.append((next_nid, *pos))
            next_nid += 1

    wire_elements: list[tuple[int, int, int]] = []
    wire_eids: list[int] = []
    eid = elem_id_start

    for beam in beams:
        _, n1, n2, _, _ = beam
        wire_elements.append((eid, lattice_nid[int(n1)], lattice_nid[int(n2)]))
        wire_eids.append(eid)
        eid += 1

    return extra_nodes, wire_elements, wire_eids
