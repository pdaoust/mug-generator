"""Nudge handle stations toward the mug surface at attachment points.

Uses a hyperbolic paraboloid (hypar) interpolation so that:
- Inner/outer rails (v = ±0.5) stay exactly where the artist placed them
- Side rail points are conformed onto the mug surface
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
    station: list[list[float]],
    norm_profile: list[tuple[float, float]],
    outer_profile: list[list[float]],
    axis_x: float,
) -> float:
    """Compute radial excess at the side rail midline (v ≈ 0) of a station.

    Finds the profile points closest to v=0 (the side rail midline,
    which sticks out furthest in Y), computes each one's radial distance
    from the mug axis vs the mug surface radius at that Z height, and
    returns the average excess.  Positive = outside the mug surface.
    """
    # Collect points near v=0 (side rail midline).  Use all points
    # with |v| < 0.1 to get a robust average, falling back to the
    # single closest point if the profile has no points that close.
    candidates: list[tuple[float, int]] = []
    for j, (u, v) in enumerate(norm_profile):
        candidates.append((abs(v), j))
    candidates.sort()

    # Take points with |v| < 0.1, or at least the closest one
    threshold = 0.1
    selected = [j for av, j in candidates if av < threshold]
    if not selected:
        selected = [candidates[0][1]]

    total_excess = 0.0
    for j in selected:
        pt = station[j]
        dx = pt[0] - axis_x
        dy = pt[1]
        r = math.sqrt(dx * dx + dy * dy)
        R = _mug_r_at_z(outer_profile, pt[2])
        total_excess += r - R

    return total_excess / len(selected)


def nudge_handle_stations(
    stations: list[list[list[float]]],
    outer_profile: list[list[float]],
    axis_x: float,
    station_frames: list["Station"] | None = None,
    norm_profile: list[tuple[float, float]] | None = None,
) -> list[list[list[float]]]:
    """Nudge handle stations so endpoint cross-sections conform to the mug.

    At each endpoint, the radial excess is measured at the side rail
    midline (v ≈ 0) — these are the points that stick out furthest
    from the mug surface.  This single excess value is then applied
    to all points in the station, weighted by the hypar term (1 - 4v²)
    so inner/outer rails (v = ±0.5) get zero correction.

    Two independent blends (top→midpoint and bottom→midpoint) decay
    the correction to zero at the handle's midpoint.

    The correction is applied radially (toward/away from mug axis)
    using the station centroid's direction, preserving cross-section shape.

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

    # Single excess value at each endpoint, measured at side rail midline
    top_excess = _side_rail_excess(
        stations[0], norm_profile, outer_profile, axis_x,
    )
    bot_excess = _side_rail_excess(
        stations[n - 1], norm_profile, outer_profile, axis_x,
    )

    # Pre-compute hypar weights for each profile point
    hypar = [1.0 - 4.0 * v * v for _u, v in norm_profile]

    result: list[list[list[float]]] = []
    for i in range(n):
        frac = i / (n - 1)
        blend_top = max(0.0, 1.0 - 2.0 * frac)
        blend_bot = max(0.0, 2.0 * frac - 1.0)

        if blend_top < 1e-6 and blend_bot < 1e-6:
            result.append(stations[i])
            continue

        # Blended excess for this station
        excess = blend_top * top_excess + blend_bot * bot_excess

        if abs(excess) < 1e-6:
            result.append(stations[i])
            continue

        # Radial direction from station centroid (uniform for all points)
        cx, cy, _ = station_frames[i].centroid
        cdx = cx - axis_x
        cdy = cy
        cr = math.sqrt(cdx * cdx + cdy * cdy)
        if cr < 0.001:
            result.append(stations[i])
            continue
        rad_x = cdx / cr
        rad_y = cdy / cr

        nudged: list[list[float]] = []
        for j, pt in enumerate(stations[i]):
            w = hypar[j]
            correction = excess * w

            if abs(correction) < 1e-6:
                nudged.append(list(pt))
                continue

            nudged.append([
                pt[0] - correction * rad_x,
                pt[1] - correction * rad_y,
                pt[2],
            ])

        result.append(nudged)

    return result
