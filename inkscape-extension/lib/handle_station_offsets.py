"""Offset handle-station variants consumed by case_mould_efficient.scad.

The efficient case mould needs four copies of the handle sweep, each
scaled by a different scalar offset of the cross-section extents.  The
body-inner-wall variant also grows one extra station at each end so the
inset handle interior punches through the body wall.
"""

from __future__ import annotations

import math
from copy import copy

from .rail_sampler import Station


def offset_stations(stations: list[Station], d: float) -> list[Station]:
    """Return stations with sx/sz scalar-offset by 2*d.

    Frames and centroids stay put — only the cross-section extents
    grow or shrink.  A minimum extent of 0.001 mm guards against
    degenerate geometry when the offset would otherwise collapse the
    profile.
    """
    result: list[Station] = []
    for s in stations:
        new_s = copy(s)
        new_s.sx = max(0.001, s.sx + 2.0 * d)
        new_s.sz = max(0.001, s.sz + 2.0 * d)
        result.append(new_s)
    return result


def extend_station_endpoints(
    stations: list[Station], distance: float,
) -> list[Station]:
    """Prepend/append one station at each end, stepped further by ``distance``.

    The new endpoint shares its neighbour's frame and extents; only the
    centroid is translated along the vector from the second-to-last
    centroid to the last, normalized, times ``distance``.
    """
    if len(stations) < 2 or distance <= 0.0:
        return list(stations)

    def _step(a: Station, b: Station, dist: float) -> tuple[float, float, float]:
        dx = b.centroid[0] - a.centroid[0]
        dy = b.centroid[1] - a.centroid[1]
        dz = b.centroid[2] - a.centroid[2]
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length < 1e-12:
            return b.centroid
        f = dist / length
        return (
            b.centroid[0] + dx * f,
            b.centroid[1] + dy * f,
            b.centroid[2] + dz * f,
        )

    start_extra = copy(stations[0])
    start_extra.centroid = _step(stations[1], stations[0], distance)
    end_extra = copy(stations[-1])
    end_extra.centroid = _step(stations[-2], stations[-1], distance)

    return [start_extra, *stations, end_extra]
