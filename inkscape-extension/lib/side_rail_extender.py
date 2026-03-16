"""Side rail interpolation for handle width profiles."""

from __future__ import annotations


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
