"""Polyline simplification that merges dense bezier segments on curves
while preserving corners and straight segments unchanged."""

from __future__ import annotations

import math


def resample_polyline(
    pts: list[tuple[float, float]],
    max_seg_len: float,
    closed: bool = False,
) -> list[tuple[float, float]]:
    """Simplify a polyline by merging short curve segments.

    Dense runs of tiny segments (from bezier flattening) are merged
    until the chord reaches *max_seg_len*.  Corner points (where the
    tangent direction changes by ≥ 15°) are always preserved, and long
    straight segments are never touched.

    Args:
        pts: Input polyline [(x, y), ...].
        max_seg_len: Maximum chord length between kept points.
        closed: If True, treat as a closed loop.  The returned list
                does **not** include a duplicate closing point.

    Returns:
        Simplified polyline with all corners and straight segments
        intact.
    """
    if len(pts) < 3 or max_seg_len <= 0:
        return list(pts)

    n = len(pts)
    # 15° deviation ≈ the boundary between gentle bezier curvature
    # and a real design corner.
    _CORNER_COS = math.cos(math.radians(15.0))

    def _is_corner(i: int) -> bool:
        """True if tangent direction changes by ≥ 15° at index *i*."""
        if not closed and (i == 0 or i == n - 1):
            return True  # endpoints always kept
        p = pts[(i - 1) % n]
        c = pts[i]
        q = pts[(i + 1) % n]
        v1x, v1y = c[0] - p[0], c[1] - p[1]
        v2x, v2y = q[0] - c[0], q[1] - c[1]
        d1, d2 = math.hypot(v1x, v1y), math.hypot(v2x, v2y)
        if d1 < 1e-9 or d2 < 1e-9:
            return False
        cos_a = (v1x * v2x + v1y * v2y) / (d1 * d2)
        return cos_a < _CORNER_COS

    # --- Open polyline ---
    if not closed:
        result = [pts[0]]
        for i in range(1, n):
            dist = math.hypot(pts[i][0] - result[-1][0],
                              pts[i][1] - result[-1][1])
            if i == n - 1 or _is_corner(i) or dist >= max_seg_len:
                result.append(pts[i])
        return result

    # --- Closed polyline ---
    keep = [_is_corner(i) for i in range(n)]
    if not any(keep):
        keep[0] = True

    start = next(i for i in range(n) if keep[i])
    last_kept = start
    for offset in range(1, n):
        i = (start + offset) % n
        if keep[i]:
            last_kept = i
            continue
        dist = math.hypot(pts[i][0] - pts[last_kept][0],
                          pts[i][1] - pts[last_kept][1])
        if dist >= max_seg_len:
            keep[i] = True
            last_kept = i

    return [pts[i] for i in range(n) if keep[i]]
