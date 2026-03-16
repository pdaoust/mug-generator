"""Side rail interpolation and handle-to-mug penetration calculation."""

from __future__ import annotations

import math


def _interp_1d(xs: list[float], ys: list[float], x: float) -> float:
    """Linear interpolation/extrapolation on sorted (xs, ys) pairs."""
    if x <= xs[0]:
        if len(xs) < 2:
            return ys[0]
        dx = xs[1] - xs[0]
        if abs(dx) < 1e-12:
            return ys[0]
        slope = (ys[1] - ys[0]) / dx
        return ys[0] + slope * (x - xs[0])
    if x >= xs[-1]:
        if len(xs) < 2:
            return ys[-1]
        dx = xs[-1] - xs[-2]
        if abs(dx) < 1e-12:
            return ys[-1]
        slope = (ys[-1] - ys[-2]) / dx
        return ys[-1] + slope * (x - xs[-1])

    for i in range(1, len(xs)):
        if xs[i] >= x:
            dx = xs[i] - xs[i - 1]
            if abs(dx) < 1e-12:
                return ys[i]
            t = (x - xs[i - 1]) / dx
            return ys[i - 1] + t * (ys[i] - ys[i - 1])
    return ys[-1]


def _normalize_side_rails(
    left_rail: list[tuple[float, float]],
    right_rail: list[tuple[float, float]],
) -> tuple[list[float], list[float], list[float], list[float]]:
    """Normalize side rail Y values to [0,1] and return sorted arrays.

    Returns:
        (left_fracs, left_widths, right_fracs, right_widths)
    """
    all_ys = [p[1] for p in left_rail] + [p[1] for p in right_rail]
    y_min = min(all_ys)
    y_max = max(all_ys)
    y_range = y_max - y_min

    def normalize_y(y: float) -> float:
        if y_range < 1e-12:
            return 0.5
        return (y - y_min) / y_range

    left_sorted = sorted(left_rail, key=lambda p: p[1])
    right_sorted = sorted(right_rail, key=lambda p: p[1])

    return (
        [normalize_y(p[1]) for p in left_sorted],
        [p[0] for p in left_sorted],
        [normalize_y(p[1]) for p in right_sorted],
        [p[0] for p in right_sorted],
    )


def _side_rail_half_width_at(
    left_fracs: list[float], left_widths: list[float],
    right_fracs: list[float], right_widths: list[float],
    frac: float,
) -> float:
    """Get the average side rail half-width at a given arc-length fraction."""
    left_w = _interp_1d(left_fracs, left_widths, frac)
    right_w = _interp_1d(right_fracs, right_widths, frac)
    return (abs(left_w) + abs(right_w)) / 2


def penetration_depth(mug_radius: float, half_width: float) -> float:
    """Calculate how far the rail endpoints must extend into the mug body.

    At a given Z height, the mug cross-section is a circle of radius R.
    The handle cross-section extends ±half_width in Y from the centerline.
    For the handle edges to be flush with the circular mug surface, the
    centerline must be at X = sqrt(R² - w²).  The penetration distance
    from the surface (at X = R) inward is:

        R - sqrt(R² - w²)  =  R · (1 - cos(arcsin(w / R)))

    If w >= R the handle is wider than the mug, so we clamp to R
    (full penetration to the axis).

    Args:
        mug_radius: Outer mug body radius at this Z height, in mm.
        half_width: Handle half-width from side rails, in mm.

    Returns:
        Penetration distance in mm (always >= 0).
    """
    if mug_radius <= 0:
        return 0.0
    if half_width >= mug_radius:
        return mug_radius
    return mug_radius - math.sqrt(mug_radius ** 2 - half_width ** 2)


def extend_rails_into_body(
    inner: list[tuple[float, float]],
    outer: list[tuple[float, float]],
    left_rail: list[tuple[float, float]],
    right_rail: list[tuple[float, float]],
    mug_outer_radius_at_z,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Extend inner/outer rail endpoints horizontally into the mug body.

    Prepends/appends a horizontal segment to each rail so that the
    handle skin penetrates the mug body deeply enough for the side
    rail edges to be flush with the mug surface.

    The side rails are not modified — they map to the full length of
    the extended midpoint curve via normal arc-length normalization,
    so the cross-section maintains its width through the extension.

    Args:
        inner: Inner rail polyline [(x, z), ...] in mm.
        outer: Outer rail polyline [(x, z), ...] in mm.
        left_rail: Left side rail [(half_width, y_position), ...].
        right_rail: Right side rail [(half_width, y_position), ...].
        mug_outer_radius_at_z: Callable(z) -> radius in mm, or None.
            Should return the outer mug body radius at the given Z height.
            This is the absolute radius (not relative to axis).

    Returns:
        (extended_inner, extended_outer) with horizontal segments added.
    """
    if mug_outer_radius_at_z is None:
        return inner, outer

    left_fracs, left_widths, right_fracs, right_widths = _normalize_side_rails(
        left_rail, right_rail
    )

    def extend_rail(rail, frac):
        """Extend one end of a rail inward by the penetration depth."""
        x, z = rail[0] if frac == 0.0 else rail[-1]
        w = _side_rail_half_width_at(
            left_fracs, left_widths, right_fracs, right_widths, frac
        )
        r = mug_outer_radius_at_z(z)
        if r is None or r <= 0:
            return rail

        depth = penetration_depth(r, w)
        if depth < 1e-6:
            return rail

        # Extend horizontally toward the axis (decreasing X)
        new_point = (x - depth, z)
        if frac == 0.0:
            return [new_point] + list(rail)
        else:
            return list(rail) + [new_point]

    inner_ext = extend_rail(inner, 0.0)
    inner_ext = extend_rail(inner_ext, 1.0)
    outer_ext = extend_rail(outer, 0.0)
    outer_ext = extend_rail(outer_ext, 1.0)

    return inner_ext, outer_ext


def apply_side_rails(
    stations: list,
    left_rail: list[tuple[float, float]],
    right_rail: list[tuple[float, float]],
) -> list:
    """Fill in sz (profile half-width) for each station from side rails.

    Side rails are in the coordinate space:
    - X = profile half-width in mm
    - Y = arbitrary position along the handle (will be normalized to [0,1])

    The Y values of both side rails are normalized together: the overall
    min Y maps to 0 (start of handle) and max Y maps to 1 (end of handle).
    The average of left and right rail widths at each station gives sz.

    Args:
        stations: Stations with arc_length_fraction set.
        left_rail: Left side rail [(half_width, y_position), ...].
        right_rail: Right side rail [(half_width, y_position), ...].

    Returns:
        Updated stations list with sz filled in.
    """
    left_fracs, left_widths, right_fracs, right_widths = _normalize_side_rails(
        left_rail, right_rail
    )

    for station in stations:
        station.sz = _side_rail_half_width_at(
            left_fracs, left_widths, right_fracs, right_widths,
            station.arc_length_fraction,
        )

    return stations
