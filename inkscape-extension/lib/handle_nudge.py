"""Nudge handle stations toward the mug surface at attachment points.

Uses a hyperbolic paraboloid (hypar) interpolation so that:
- Inner/outer rails (v = ±0.5) stay exactly where the artist placed them
- Side rail endpoints (u = ±0.5) are stretched onto the mug surface
- Intermediate profile points blend smoothly between these constraints
- Corrections decay to zero at the handle midpoint (two separate blends)
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .rail_sampler import Station


def _mug_r_at_z(profile: list[list[float]], z: float) -> float:
    """Interpolate mug outer radius at height z from profile polygon.

    Walks actual polygon segments (matching the SCAD mug_r_at_z) and
    returns the maximum radius found, correctly ignoring axis-closure
    segments.
    """
    n = len(profile)
    results: list[float] = []
    for i in range(n):
        j = (i + 1) % n
        z0, z1 = profile[i][1], profile[j][1]
        zlo, zhi = min(z0, z1), max(z0, z1)
        if zlo <= z <= zhi and abs(zhi - zlo) > 1e-9:
            t = (z - z0) / (z1 - z0)
            r = profile[i][0] + t * (profile[j][0] - profile[i][0])
            results.append(r)
    return max(results) if results else profile[0][0]


def _side_rail_excess(
    frame: "Station",
    outer_profile: list[list[float]],
    axis_x: float,
) -> tuple[float, float]:
    """Compute radial excess for left/right side rail midpoints.

    Returns (excess_left, excess_right) where positive means the point
    is outside the mug surface and negative means inside.
    """
    cx, cy, cz = frame.centroid
    z_axis = frame.z_axis
    sz = frame.sz

    results: list[float] = []
    for sign in (-0.5, 0.5):  # u = -0.5 (left), u = +0.5 (right)
        # Side rail midpoint in 3D (v=0 → no x_axis component)
        px = cx + sign * sz * z_axis[0]
        py = cy + sign * sz * z_axis[1]
        pz = cz + sign * sz * z_axis[2]

        dx = px - axis_x
        dy = py
        r = math.sqrt(dx * dx + dy * dy)
        R = _mug_r_at_z(outer_profile, pz)
        results.append(r - R)

    return results[0], results[1]


def nudge_handle_stations(
    stations: list[list[list[float]]],
    outer_profile: list[list[float]],
    axis_x: float,
    station_frames: list["Station"] | None = None,
    norm_profile: list[tuple[float, float]] | None = None,
) -> list[list[list[float]]]:
    """Nudge handle stations so endpoint cross-sections conform to the mug.

    Each profile point at normalized coordinates (u, v) receives a radial
    nudge (toward or away from the mug axis)::

        correction(u, v) = excess_side(u) * (1 - 4*v**2)

    where ``excess_side(u)`` linearly interpolates between the left and
    right side-rail radial excesses, and ``(1 - 4*v**2)`` is a hypar
    surface that preserves the inner/outer rails (v = ±0.5) while giving
    full correction at the side-rail midline (v = 0).

    Two independent blends (top→midpoint and bottom→midpoint) ensure the
    correction decays to zero at the handle's midpoint.

    Args:
        stations: List of cross-sections, each a list of [x, y, z] points.
        outer_profile: Mug outer profile as [[r, z], ...] polygon.
        axis_x: X coordinate of the mug axis.
        station_frames: Station objects carrying frame data.
        norm_profile: Normalized (u, v) profile coordinates, one per point.

    Returns:
        Nudged stations (same structure).
    """
    n = len(stations)
    if n < 3 or station_frames is None or norm_profile is None:
        return stations

    # Radial excess at side-rail midpoints of each endpoint
    ex_left_top, ex_right_top = _side_rail_excess(
        station_frames[0], outer_profile, axis_x,
    )
    ex_left_bot, ex_right_bot = _side_rail_excess(
        station_frames[n - 1], outer_profile, axis_x,
    )

    import sys
    print(f"DEBUG nudge: n={n} stations", file=sys.stderr)
    print(f"  endpoint 0 centroid={station_frames[0].centroid}", file=sys.stderr)
    print(f"  endpoint 0 sz={station_frames[0].sz:.3f}", file=sys.stderr)
    print(f"  endpoint 0 z_axis={station_frames[0].z_axis}", file=sys.stderr)
    print(f"  ex_left_top={ex_left_top:.4f}  ex_right_top={ex_right_top:.4f}", file=sys.stderr)
    print(f"  endpoint {n-1} centroid={station_frames[n-1].centroid}", file=sys.stderr)
    print(f"  ex_left_bot={ex_left_bot:.4f}  ex_right_bot={ex_right_bot:.4f}", file=sys.stderr)

    # Show norm_profile range
    us = [uv[0] for uv in norm_profile]
    vs = [uv[1] for uv in norm_profile]
    print(f"  norm_profile: {len(norm_profile)} pts, u=[{min(us):.3f},{max(us):.3f}], v=[{min(vs):.3f},{max(vs):.3f}]", file=sys.stderr)

    result: list[list[list[float]]] = []
    for i in range(n):
        frac = i / (n - 1)
        blend_top = max(0.0, 1.0 - 2.0 * frac)
        blend_bot = max(0.0, 2.0 * frac - 1.0)

        if blend_top < 1e-6 and blend_bot < 1e-6:
            result.append(stations[i])
            continue

        # Debug: show first 10 stations near each endpoint
        show_debug = (i < 10) or (i > n - 11)

        nudged: list[list[float]] = []
        max_excess = 0.0
        min_excess = 0.0
        for j, pt in enumerate(stations[i]):
            u, v = norm_profile[j]

            # Hypar: 0 at inner/outer rails (v=±0.5), 1 at midline (v=0)
            hypar = 1.0 - 4.0 * v * v

            # Linear interpolation of side-rail excess across u
            ex_top = ex_left_top * (0.5 - u) + ex_right_top * (0.5 + u)
            ex_bot = ex_left_bot * (0.5 - u) + ex_right_bot * (0.5 + u)

            excess = (blend_top * ex_top + blend_bot * ex_bot) * hypar
            max_excess = max(max_excess, excess)
            min_excess = min(min_excess, excess)

            if abs(excess) < 1e-6:
                nudged.append(list(pt))
                continue

            # Radial direction at this point (XY plane, away from mug axis)
            dx = pt[0] - axis_x
            dy = pt[1]
            r = math.sqrt(dx * dx + dy * dy)
            if r < 0.001:
                nudged.append(list(pt))
                continue

            rad_x = dx / r
            rad_y = dy / r

            # Subtract excess to bring point onto surface
            nudged.append([
                pt[0] - excess * rad_x,
                pt[1] - excess * rad_y,
                pt[2],
            ])

        if show_debug:
            orig_xs = [pt[0] for pt in stations[i]]
            orig_ys = [pt[1] for pt in stations[i]]
            nudged_xs = [pt[0] for pt in nudged]
            nudged_ys = [pt[1] for pt in nudged]
            print(f"  station {i}: frac={frac:.3f} blend_top={blend_top:.3f} blend_bot={blend_bot:.3f}"
                  f" excess=[{min_excess:.3f},{max_excess:.3f}]",
                  file=sys.stderr)
            print(f"    X: orig=[{min(orig_xs):.3f},{max(orig_xs):.3f}]"
                  f" nudged=[{min(nudged_xs):.3f},{max(nudged_xs):.3f}]"
                  f"  Y: orig=[{min(orig_ys):.3f},{max(orig_ys):.3f}]"
                  f" nudged=[{min(nudged_ys):.3f},{max(nudged_ys):.3f}]",
                  file=sys.stderr)
            # Show a few representative points: side rail (max |u|) and inner/outer (max |v|)
            if i < 6:
                print(f"    per-point detail (u, v, excess, dx, dy):", file=sys.stderr)
                for j2, pt2 in enumerate(stations[i]):
                    u2, v2 = norm_profile[j2]
                    h2 = 1.0 - 4.0 * v2 * v2
                    ex_t = ex_left_top * (0.5 - u2) + ex_right_top * (0.5 + u2)
                    ex_b = ex_left_bot * (0.5 - u2) + ex_right_bot * (0.5 + u2)
                    exc2 = (blend_top * ex_t + blend_bot * ex_b) * h2
                    dx2 = nudged[j2][0] - pt2[0]
                    dy2 = nudged[j2][1] - pt2[1]
                    if abs(exc2) > 0.01 or abs(u2) > 0.45 or abs(v2) > 0.45:
                        print(f"      pt{j2}: u={u2:.3f} v={v2:.3f} hypar={h2:.3f}"
                              f" excess={exc2:.3f} dx={dx2:.3f} dy={dy2:.3f}"
                              f" orig=({pt2[0]:.2f},{pt2[1]:.2f},{pt2[2]:.2f})"
                              f" nudged=({nudged[j2][0]:.2f},{nudged[j2][1]:.2f})",
                              file=sys.stderr)

        result.append(nudged)

    return result
