"""Handle profile normalization and per-station transformation."""

from __future__ import annotations

import math

from .rail_sampler import Station


def _shoelace_area(pts: list[tuple[float, float]]) -> float:
    """Signed area via shoelace formula. Positive = CCW."""
    n = len(pts)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += pts[i][0] * pts[j][1]
        area -= pts[j][0] * pts[i][1]
    return area / 2.0


def normalize_profile(profile: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Normalize a 2D profile to unit bounding box centered at origin, CCW winding.

    Args:
        profile: Closed polygon [(x, y), ...]. Last point need not repeat first.

    Returns:
        Normalized profile in unit bounding box [-0.5, 0.5] x [-0.5, 0.5], CCW.
    """
    if len(profile) < 3:
        raise ValueError("Profile must have at least 3 points")

    xs = [p[0] for p in profile]
    ys = [p[1] for p in profile]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    w = max_x - min_x
    h = max_y - min_y

    if w < 1e-12 or h < 1e-12:
        raise ValueError("Profile has zero width or height")

    cx = (min_x + max_x) / 2
    cy = (min_y + max_y) / 2

    # Normalize each axis independently to [-0.5, 0.5] so the profile
    # fills the full extent in both the sx and sz directions.
    normalized = [((p[0] - cx) / w, (p[1] - cy) / h) for p in profile]

    # Enforce CCW winding
    if _shoelace_area(normalized) < 0:
        normalized.reverse()

    return normalized


def transform_profile_at_station(
    profile: list[tuple[float, float]],
    station: Station,
) -> list[tuple[float, float, float]]:
    """Transform a normalized 2D profile to 3D at a station.

    Profile coordinates (as drawn in the SVG):
    - u (first coord / X) = width of handle strap → maps to z_axis, scaled by sz
      (protrusion from the drawing plane, controlled by side rails)
    - v (second coord / Y) = thickness → maps to x_axis, scaled by sx
      (inner-to-outer rail direction)

    Args:
        profile: Normalized profile from normalize_profile().
        station: Station with frame and scale.

    Returns:
        List of 3D points [(x, y, z), ...] in mm.
    """
    result = []
    for u, v in profile:
        # u (profile X) → z_axis / sz (side rail width, ±Y protrusion)
        # v (profile Y) → x_axis / sx (inner-outer rail thickness)
        su = u * station.sz
        sv = v * station.sx

        # Transform: centroid + sv * x_axis + su * z_axis
        x = station.centroid[0] + sv * station.x_axis[0] + su * station.z_axis[0]
        y = station.centroid[1] + sv * station.x_axis[1] + su * station.z_axis[1]
        z = station.centroid[2] + sv * station.x_axis[2] + su * station.z_axis[2]
        result.append((x, y, z))

    return result


def transform_profile_blended(
    profile: list[tuple[float, float]],
    station: Station,
    mug_axis_x: float,
    mug_radius: float,
    blend: float,
) -> list[tuple[float, float, float]]:
    """Transform a profile to 3D, blending the width axis onto the mug cylinder.

    At blend=0 the profile is flat (width along station z_axis).
    At blend=1 the width axis is tangential to the mug cylinder and
    curved by the sagitta, producing a saddle shape.

    The width direction is smoothly rotated from the station frame's
    z_axis toward the cylinder tangent, so the profile doesn't collapse
    at intermediate blend values.

    Args:
        profile: Normalized profile from normalize_profile().
        station: Station with frame and scale.
        mug_axis_x: X coordinate of the mug's axis of revolution.
        mug_radius: Outer mug radius at this station's Z height.
        blend: 0 = flat, 1 = fully wrapped.

    Returns:
        List of 3D points [(x, y, z), ...] in mm.
    """
    cx, cy, cz = station.centroid

    # Direction from centroid toward the mug axis (XY plane only)
    to_ax = mug_axis_x - cx
    to_ay = -cy
    to_len = math.sqrt(to_ax * to_ax + to_ay * to_ay)
    if to_len > 1e-9:
        inward_x = to_ax / to_len
        inward_y = to_ay / to_len
    else:
        inward_x, inward_y = 0.0, 0.0

    # Cylinder tangent at centroid (perpendicular to radial, in XY plane)
    tangent = (-inward_y, inward_x, 0.0)

    # Align tangent sign with z_axis so the blend rotates smoothly
    z_dot = (station.z_axis[0] * tangent[0]
             + station.z_axis[1] * tangent[1]
             + station.z_axis[2] * tangent[2])
    if z_dot < 0:
        tangent = (inward_y, -inward_x, 0.0)

    result = []
    for u, v in profile:
        su = u * station.sz   # width offset
        sv = v * station.sx   # thickness offset

        # Blend width direction from station z_axis toward cylinder tangent
        wd_x = (1.0 - blend) * station.z_axis[0] + blend * tangent[0]
        wd_y = (1.0 - blend) * station.z_axis[1] + blend * tangent[1]
        wd_z = (1.0 - blend) * station.z_axis[2] + blend * tangent[2]
        wd_len = math.sqrt(wd_x * wd_x + wd_y * wd_y + wd_z * wd_z)
        if wd_len > 1e-12:
            wd_x /= wd_len
            wd_y /= wd_len
            wd_z /= wd_len

        # Position = centroid + thickness along x_axis + width along blended dir
        x = cx + sv * station.x_axis[0] + su * wd_x
        y = cy + sv * station.x_axis[1] + su * wd_y
        z = cz + sv * station.x_axis[2] + su * wd_z

        # Sagitta correction for the tangential component of the width offset.
        # Only the part of the offset that's tangential to the cylinder needs
        # curvature correction (pushing inward).
        # Use the centroid's actual radial distance (to_len) rather than
        # the mug profile radius — on concave bodies mug_radius changes
        # sharply near the equator, causing jagged cross-section transitions.
        su_tan = su * (wd_x * tangent[0] + wd_y * tangent[1])
        if to_len > 1e-9:
            sagitta = to_len * (1.0 - math.cos(su_tan / to_len))
        else:
            sagitta = 0.0

        x += sagitta * inward_x
        y += sagitta * inward_y

        result.append((x, y, z))

    return result


def generate_handle_stations(
    profile: list[tuple[float, float]],
    stations: list[Station],
    mug_axis_x: float | None = None,
    mug_radius_at_z=None,
) -> list[list[tuple[float, float, float]]]:
    """Generate all handle cross-section polygons for skin() loft.

    When mug geometry is provided, each station's profile is blended
    between flat (at the midpoint of the handle) and cylinder-wrapped
    (at the endpoints where the handle meets the mug).

    Args:
        profile: Raw profile polygon (will be normalized).
        stations: List of Station objects with frames and scales.
        mug_axis_x: X coordinate of the mug axis (needed for wrapping).
        mug_radius_at_z: Callable(z) -> radius, or None to skip wrapping.

    Returns:
        List of N closed 3D polygons, one per station.
    """
    norm = normalize_profile(profile)
    can_wrap = mug_axis_x is not None and mug_radius_at_z is not None

    result = []
    for s in stations:
        if can_wrap:
            mug_r = mug_radius_at_z(s.centroid[2])
            if mug_r is not None and mug_r > 0:
                # blend: 0 at midpoint (frac=0.5), 1 at endpoints (frac=0,1)
                blend = 2.0 * abs(s.arc_length_fraction - 0.5)
                result.append(transform_profile_blended(
                    norm, s, mug_axis_x, mug_r, blend,
                ))
                continue

        result.append(transform_profile_at_station(norm, s))

    return result
