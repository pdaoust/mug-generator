"""Analytic cubic-Bezier evaluation for pre-render decisions.

Python-side counterpart to ``scad/lib/handle_geom.scad``.  Used by the
Inkscape extension for the small set of decisions that must happen
*before* OpenSCAD runs: foot-concavity detection, lip/foot (r, z)
extrema feeding mould parameters, etc.

Bezpath layout (BOSL2 standard, cubic / N=3): a flat list of [x, y]
points laid out as ``[k0, c0a, c0b, k1, c1a, c1b, k2, ...]``.
A closed bezpath repeats its first knot at the end.

A Bezier segment can dip below or rise above its endpoint knots, so
walking just the knots (or the off-curve control points) misses real
curve extrema.  These helpers solve the per-segment derivative cubic in
closed form (it's a quadratic), giving exact answers without
``$fa``/``$fs`` resolution logic.
"""

from __future__ import annotations

import math


def cubic_point(curve, u):
    """Evaluate a cubic Bezier ``[p0, p1, p2, p3]`` at parameter u in [0,1]."""
    p0, p1, p2, p3 = curve
    mu = 1.0 - u
    a = mu * mu * mu
    b = 3 * mu * mu * u
    c = 3 * mu * u * u
    d = u * u * u
    return (
        a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
        a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
    )


def _cubic_axis_extrema_us(curve, axis):
    """Roots in (0,1) of d/du of one coordinate.

    The derivative of a cubic Bezier is a quadratic; its roots are the
    candidate parameters where that coordinate is locally extremal.
    """
    p0 = curve[0][axis]
    p1 = curve[1][axis]
    p2 = curve[2][axis]
    p3 = curve[3][axis]
    # B'(u) = 3((1-u)^2 (p1-p0) + 2(1-u)u (p2-p1) + u^2 (p3-p2))
    # Expand to A u^2 + B u + C = 0 (after dividing by 3):
    a = (-p0 + 3 * p1 - 3 * p2 + p3)
    b = 2 * (p0 - 2 * p1 + p2)
    c = (p1 - p0)
    out = []
    if abs(a) < 1e-14:
        if abs(b) > 1e-14:
            u = -c / b
            if 0 < u < 1:
                out.append(u)
    else:
        disc = b * b - 4 * a * c
        if disc >= 0:
            sq = math.sqrt(disc)
            for u in ((-b + sq) / (2 * a), (-b - sq) / (2 * a)):
                if 0 < u < 1:
                    out.append(u)
    return out


def _segments(bezpath):
    """Yield consecutive cubic segments [p0,p1,p2,p3] from a bezpath."""
    n = (len(bezpath) - 1) // 3
    for i in range(n):
        yield bezpath[3 * i: 3 * i + 4]


def bezpath_extrema_axis(bezpath, axis):
    """All on-curve points where ``axis`` (0=x/r, 1=y/z) is locally extremal.

    Includes both knot endpoints and mid-curve roots of the per-segment
    derivative.  Returns a list of (x, y) tuples.
    """
    pts = []
    for seg in _segments(bezpath):
        pts.append(tuple(seg[0]))
        for u in _cubic_axis_extrema_us(seg, axis):
            pts.append(cubic_point(seg, u))
    pts.append(tuple(bezpath[-1]))
    return pts


def bezpath_min_axis(bezpath, axis):
    """The on-curve point with the smallest ``axis`` coordinate."""
    return min(bezpath_extrema_axis(bezpath, axis), key=lambda p: p[axis])


def bezpath_max_axis(bezpath, axis):
    """The on-curve point with the largest ``axis`` coordinate."""
    return max(bezpath_extrema_axis(bezpath, axis), key=lambda p: p[axis])


def bezpath_bbox(bezpath):
    """Tight bounding box of the curve: ((xmin, ymin), (xmax, ymax))."""
    xs = [p[0] for p in bezpath_extrema_axis(bezpath, 0)]
    ys = [p[1] for p in bezpath_extrema_axis(bezpath, 1)]
    return (min(xs), min(ys)), (max(xs), max(ys))


def bezpath_length(bezpath, samples_per_segment=20):
    """Approximate arc length by sampling each segment uniformly in u."""
    total = 0.0
    for seg in _segments(bezpath):
        prev = cubic_point(seg, 0.0)
        for k in range(1, samples_per_segment + 1):
            u = k / samples_per_segment
            cur = cubic_point(seg, u)
            total += math.hypot(cur[0] - prev[0], cur[1] - prev[1])
            prev = cur
    return total


def cubic_solve_axis(curve, axis, value):
    """Roots in [0,1] of one coordinate equalling ``value`` along the cubic.

    Solves ``B_axis(u) = value`` for u — used by mug_r_at_z (axis=1, z)
    to find every parameter where the curve crosses a given height.
    """
    p0 = curve[0][axis]
    p1 = curve[1][axis]
    p2 = curve[2][axis]
    p3 = curve[3][axis]
    # Bezier basis → power basis:
    #   B(u) = (-p0+3p1-3p2+p3)u^3 + 3(p0-2p1+p2)u^2 + 3(p1-p0)u + p0
    a = -p0 + 3 * p1 - 3 * p2 + p3
    b = 3 * (p0 - 2 * p1 + p2)
    c = 3 * (p1 - p0)
    d = p0 - value
    return _solve_cubic(a, b, c, d)


def _solve_cubic(a, b, c, d):
    """Real roots in [0, 1] of a u^3 + b u^2 + c u + d = 0."""
    if abs(a) < 1e-14:
        return _solve_quadratic(b, c, d)
    # Depressed cubic: u = t - b/(3a) → t^3 + p t + q = 0
    b1 = b / a
    c1 = c / a
    d1 = d / a
    p = c1 - b1 * b1 / 3.0
    q = 2 * b1 * b1 * b1 / 27.0 - b1 * c1 / 3.0 + d1
    disc = q * q / 4.0 + p * p * p / 27.0
    shift = -b1 / 3.0
    ts = []
    if disc > 1e-14:
        # One real root.
        sq = math.sqrt(disc)
        u1 = -q / 2.0 + sq
        u2 = -q / 2.0 - sq
        ts.append(_cbrt(u1) + _cbrt(u2))
    elif disc < -1e-14:
        # Three real roots — trigonometric.
        r = math.sqrt(-p * p * p / 27.0)
        phi = math.acos(max(-1.0, min(1.0, -q / (2 * r))))
        m = 2 * (-p / 3.0) ** 0.5
        for k in range(3):
            ts.append(m * math.cos((phi + 2 * math.pi * k) / 3.0))
    else:
        # disc ≈ 0 — repeated root.
        if abs(q) < 1e-14:
            ts.append(0.0)
        else:
            t1 = -2 * _cbrt(q / 2.0)
            t2 = _cbrt(q / 2.0)
            ts.extend([t1, t2])
    out = []
    for t in ts:
        u = t + shift
        if -1e-9 <= u <= 1 + 1e-9:
            out.append(max(0.0, min(1.0, u)))
    return out


def _solve_quadratic(a, b, c):
    if abs(a) < 1e-14:
        if abs(b) < 1e-14:
            return []
        u = -c / b
        return [u] if -1e-9 <= u <= 1 + 1e-9 else []
    disc = b * b - 4 * a * c
    if disc < 0:
        return []
    sq = math.sqrt(disc)
    out = []
    for u in ((-b + sq) / (2 * a), (-b - sq) / (2 * a)):
        if -1e-9 <= u <= 1 + 1e-9:
            out.append(max(0.0, min(1.0, u)))
    return out


def _cbrt(x):
    return math.copysign(abs(x) ** (1.0 / 3.0), x)


def bezpath_radius_at_z(bezpath, z, axis_z=1, axis_r=0, side="max"):
    """All on-curve radii where the bezpath crosses the horizontal line at ``z``.

    Returns the maximum (``side="max"``) or minimum (``side="min"``)
    radius across all crossings on all segments, or ``None`` if no
    crossings exist.  This is the analytic cousin of prototype.scad's
    polyline-walk ``mug_r_at_z``.
    """
    rs = []
    for seg in _segments(bezpath):
        for u in cubic_solve_axis(seg, axis_z, z):
            rs.append(cubic_point(seg, u)[axis_r])
    if not rs:
        return None
    return max(rs) if side == "max" else min(rs)


def detect_foot_concavity_bez(outer_bez):
    """Foot-concavity detection on the outer-side bezpath.

    ``outer_bez`` is the half of the closed body bezpath running from
    the rim (top, max z) down to the foot center (axis crossing, r≈0)
    or from foot to rim — orientation is detected automatically.
    Returns ``(z_top_of_concavity, r_foot_ring)`` if the curve dips
    below the foot-ring radius and rises back, else ``None``.

    The curve is sampled densely in its natural arc-length order; the
    bottom-most run of samples defines the foot-ring radius, then the
    walk looks for an under-cut (r dipping below r_foot) that resolves
    by crossing back to r_foot at higher z.
    """
    samples = []
    for seg in _segments(outer_bez):
        for k in range(33):
            u = k / 32.0
            samples.append(cubic_point(seg, u))
    if len(samples) < 3:
        return None

    # r_foot = max radius among samples at the bottom z of the curve.
    # For a foot-ring mug this is the foot ring's outer radius; for a
    # plain taper to the axis, this is the radius at z_min (often 0
    # or near it, but nonzero is possible too).
    z_min = min(p[1] for p in samples)
    foot_band = max(1e-3, 1e-3 * abs(z_min))
    r_foot = max(p[0] for p in samples if p[1] <= z_min + foot_band)

    # Concavity = the highest z at which the curve still sits inside
    # r < r_foot.  No such z above z_min ⇒ no concavity.
    inside = [p for p in samples
              if p[0] < r_foot - 1e-6 and p[1] > z_min + foot_band]
    if not inside:
        return None
    z_top = max(p[1] for p in inside)
    return (z_top, r_foot)


def split_outer_bez_at_rim(closed_bez):
    """Slice a closed body bezpath into its outer half (rim → axis).

    Returns the bezpath of the outer side, running from the rim (max z)
    down to the foot center (r ≈ 0).  Used to feed
    ``detect_foot_concavity_bez`` and lip/foot extrema queries.

    Heuristic: walk the bezpath segments forward from the segment whose
    knot has max z, accumulating segments until r drops below
    AXIS_THRESHOLD; if the forward direction has larger swept area than
    the reverse, that's the outer side.
    """
    AXIS_THRESHOLD = 0.1
    n_segs = (len(closed_bez) - 1) // 3
    knots = [closed_bez[3 * i] for i in range(n_segs)]
    # Find the rim knot (max z, tiebreak max r).
    rim = max(range(len(knots)), key=lambda i: (knots[i][1], knots[i][0]))

    def walk(start, step):
        segs = []
        i = start
        while True:
            seg_idx = i % n_segs if step > 0 else (i - 1) % n_segs
            seg = closed_bez[3 * seg_idx: 3 * seg_idx + 4]
            if step < 0:
                seg = list(reversed(seg))
            segs.append(seg)
            end = seg[-1]
            if end[0] < AXIS_THRESHOLD:
                break
            i += step
            if abs(i - start) > n_segs:
                break
        return segs

    fwd = walk(rim, +1)
    bwd = walk(rim, -1)

    def swept_area(segs):
        # Sample each cubic at a few u and integrate trapezoids in (r, z).
        pts = []
        for seg in segs:
            for k in range(9):
                pts.append(cubic_point(seg, k / 8.0))
        # Foot-concavity flatten: enforce monotonically decreasing z.
        z_min = pts[0][1]
        flat = [pts[0][1]]
        for p in pts[1:]:
            z_min = min(z_min, p[1])
            flat.append(z_min)
        area = 0.0
        for i in range(len(pts) - 1):
            r1, z1 = pts[i][0], flat[i]
            r2, z2 = pts[i + 1][0], flat[i + 1]
            area += (r1 + r2) / 2.0 * abs(z2 - z1)
        return area

    chosen = fwd if swept_area(fwd) >= swept_area(bwd) else bwd
    flat = [chosen[0][0]]
    for seg in chosen:
        flat.extend(seg[1:])
    return flat
