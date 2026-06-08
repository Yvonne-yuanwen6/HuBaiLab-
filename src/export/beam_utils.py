"""Beam list helpers for export and meshing."""

from __future__ import annotations


def dedupe_beams(beams: list) -> tuple[list, int]:
    """
    Remove duplicate centerline segments (shared cell faces add the same edge twice).

    Returns (unique_beams, duplicate_count).
    """
    seen: set[tuple[int, int, float, str]] = set()
    unique: list = []
    duplicates = 0
    next_id = 1

    for beam in beams:
        bid, n1, n2, radius, btype = beam
        a, b = (int(n1), int(n2)) if int(n1) < int(n2) else (int(n2), int(n1))
        key = (a, b, float(radius), str(btype))
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        unique.append([next_id, a, b, float(radius), str(btype)])
        next_id += 1

    return unique, duplicates
