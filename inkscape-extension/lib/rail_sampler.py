"""Arc-length parameterization and per-station frame computation for handle rails."""

from __future__ import annotations

import math
from dataclasses import dataclass


def _cumulative_chord_lengths(pts: list[tuple[float, float]]) -> list[float]:
    """Return cumulative chord lengths starting at 0."""
    lengths = [0.0]
    for i in range(1, len(pts)):
        dx = pts[i][0] - pts[i - 1][0]
        dy = pts[i][1] - pts[i - 1][1]
        lengths.append(lengths[-1] + math.hypot(dx, dy))
    return lengths


def _interp_polyline(
    pts: list[tuple[float, float]], cum_lengths: list[float], s: float
) -> tuple[float, float]:
    """Interpolate a point on a polyline at arc-length s."""
    total = cum_lengths[-1]
    s = max(0.0, min(s, total))

    for i in range(1, len(cum_lengths)):
        if cum_lengths[i] >= s - 1e-12:
            seg_len = cum_lengths[i] - cum_lengths[i - 1]
            if seg_len < 1e-12:
                return pts[i]
            t = (s - cum_lengths[i - 1]) / seg_len
            return (
                pts[i - 1][0] + t * (pts[i][0] - pts[i - 1][0]),
                pts[i - 1][1] + t * (pts[i][1] - pts[i - 1][1]),
            )
    return pts[-1]


def _tangent_polyline(
    pts: list[tuple[float, float]], cum_lengths: list[float], s: float
) -> tuple[float, float]:
    """Compute unit tangent on a polyline at arc-length s."""
    total = cum_lengths[-1]
    s = max(0.0, min(s, total))

    for i in range(1, len(cum_lengths)):
        if cum_lengths[i] >= s - 1e-12:
            dx = pts[i][0] - pts[i - 1][0]
            dy = pts[i][1] - pts[i - 1][1]
            length = math.hypot(dx, dy)
            if length < 1e-12:
                continue
            return (dx / length, dy / length)
    # Fallback: last segment
    dx = pts[-1][0] - pts[-2][0]
    dy = pts[-1][1] - pts[-2][1]
    length = math.hypot(dx, dy)
    if length < 1e-12:
        return (1.0, 0.0)
    return (dx / length, dy / length)


def _normalize(v: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if length < 1e-12:
        return (0.0, 0.0, 0.0)
    return (v[0] / length, v[1] / length, v[2] / length)


def _cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot3(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


@dataclass
class Station:
    """A cross-section frame along the handle path."""
    centroid: tuple[float, float, float]  # (x, y, z) in mm
    x_axis: tuple[float, float, float]    # tilt axis (inner→outer direction)
    y_axis: tuple[float, float, float]    # forward axis (along handle)
    z_axis: tuple[float, float, float]    # normal (cross product of x,y)
    sx: float  # scale in x_axis direction (inner-outer distance)
    sz: float  # scale in z_axis direction (filled in by side_rail_extender)
    arc_length_fraction: float  # [0,1] position along midpoint curve


def _build_midpoint_curve(
    inner: list[tuple[float, float]], outer: list[tuple[float, float]], n_dense: int = 200
) -> list[tuple[float, float]]:
    """Build midpoint curve between inner and outer rails.

    Samples both rails at n_dense evenly spaced arc-length points,
    then computes midpoints.
    """
    inner_cl = _cumulative_chord_lengths(inner)
    outer_cl = _cumulative_chord_lengths(outer)

    midpoints = []
    for i in range(n_dense + 1):
        t = i / n_dense
        s_in = t * inner_cl[-1]
        s_out = t * outer_cl[-1]
        p_in = _interp_polyline(inner, inner_cl, s_in)
        p_out = _interp_polyline(outer, outer_cl, s_out)
        midpoints.append(((p_in[0] + p_out[0]) / 2, (p_in[1] + p_out[1]) / 2))

    return midpoints


def sample_rails(
    inner: list[tuple[float, float]],
    outer: list[tuple[float, float]],
    n_stations: int,
) -> list[Station]:
    """Sample inner/outer rails at N evenly-spaced stations along midpoint curve.

    The rails are in the SVG coordinate space where:
    - X = radius from mug axis
    - Y = height (already inverted so Y=Z in 3D)

    Returns Station objects with 3D frames where Y=0 (drawing plane).

    Args:
        inner: Inner rail as polyline [(x, z), ...] in mm.
        outer: Outer rail as polyline [(x, z), ...] in mm.
        n_stations: Number of evenly-spaced stations to generate.
    """
    if n_stations < 2:
        raise ValueError("Need at least 2 stations")

    # Build midpoint curve at high resolution
    midpoints = _build_midpoint_curve(inner, outer)
    mid_cl = _cumulative_chord_lengths(midpoints)
    mid_total = mid_cl[-1]

    inner_cl = _cumulative_chord_lengths(inner)
    outer_cl = _cumulative_chord_lengths(outer)

    stations = []
    for i in range(n_stations):
        frac = i / (n_stations - 1)
        s_mid = frac * mid_total

        # Find the parameter t that corresponds to this midpoint arc length
        # Since midpoints were built at evenly spaced t, we can find t from s_mid
        mid_pt = _interp_polyline(midpoints, mid_cl, s_mid)

        # Sample inner/outer at same fraction along their lengths
        s_in = frac * inner_cl[-1]
        s_out = frac * outer_cl[-1]
        p_in = _interp_polyline(inner, inner_cl, s_in)
        p_out = _interp_polyline(outer, outer_cl, s_out)

        # Centroid in 3D: SVG (x,y) → 3D (x, 0, z)
        cx = (p_in[0] + p_out[0]) / 2
        cz = (p_in[1] + p_out[1]) / 2
        centroid = (cx, 0.0, cz)

        # X axis: inner→outer direction in 3D
        dx = p_out[0] - p_in[0]
        dz = p_out[1] - p_in[1]
        sx = math.hypot(dx, dz)
        if sx < 1e-12:
            x_axis = (1.0, 0.0, 0.0)
        else:
            x_axis = (dx / sx, 0.0, dz / sx)

        # Forward axis from inner+outer tangents, averaged
        t_in = _tangent_polyline(inner, inner_cl, s_in)
        t_out = _tangent_polyline(outer, outer_cl, s_out)
        # Average tangent in 3D (x, 0, z)
        fwd = ((t_in[0] + t_out[0]) / 2, 0.0, (t_in[1] + t_out[1]) / 2)

        # Gram-Schmidt: orthogonalize fwd against x_axis
        proj = _dot3(fwd, x_axis)
        fwd_orth = (fwd[0] - proj * x_axis[0], fwd[1] - proj * x_axis[1], fwd[2] - proj * x_axis[2])
        y_axis = _normalize(fwd_orth)

        # If degenerate, use a fallback
        if math.sqrt(y_axis[0] ** 2 + y_axis[1] ** 2 + y_axis[2] ** 2) < 0.5:
            y_axis = (0.0, 0.0, 1.0)

        # Z axis: cross(X, Y) — this will be in the Y direction (out of drawing plane)
        z_axis = _normalize(_cross(x_axis, y_axis))

        stations.append(Station(
            centroid=centroid,
            x_axis=x_axis,
            y_axis=y_axis,
            z_axis=z_axis,
            sx=sx,
            sz=0.0,  # filled by side_rail_extender
            arc_length_fraction=frac,
        ))

    return stations
