"""Tests for analytic cubic-Bezier evaluation."""

from __future__ import annotations

import math

import pytest

from lib.bezier_eval import (
    cubic_point,
    cubic_solve_axis,
    bezpath_extrema_axis,
    bezpath_min_axis,
    bezpath_max_axis,
    bezpath_bbox,
    bezpath_radius_at_z,
    detect_foot_concavity_bez,
    split_outer_bez_at_rim,
)


def _line_bez(a, b):
    """Cubic representation of the line segment a→b (controls at 1/3 and 2/3)."""
    return [
        a,
        ((2 * a[0] + b[0]) / 3, (2 * a[1] + b[1]) / 3),
        ((a[0] + 2 * b[0]) / 3, (a[1] + 2 * b[1]) / 3),
        b,
    ]


def test_cubic_point_endpoints():
    seg = _line_bez((0, 0), (3, 4))
    assert cubic_point(seg, 0) == pytest.approx((0, 0))
    assert cubic_point(seg, 1) == pytest.approx((3, 4))
    assert cubic_point(seg, 0.5) == pytest.approx((1.5, 2.0))


def test_cubic_solve_axis_z_crossings():
    # A vertical line cubic from (1, 0) to (1, 10) — z=5 must hit at u=0.5.
    seg = _line_bez((1, 0), (1, 10))
    us = cubic_solve_axis(seg, 1, 5.0)
    assert any(abs(u - 0.5) < 1e-6 for u in us)


def test_midcurve_extremum_detected():
    # A cubic whose Z dips below both knot Z values mid-segment.
    # Knots at z=0; control points pulled to z=-3 → curve dips below 0.
    seg = [(0, 0), (1, -3), (2, -3), (3, 0)]
    bez = list(seg)
    pts = bezpath_extrema_axis(bez, 1)
    z_min = min(p[1] for p in pts)
    # Endpoints alone would give z_min = 0; analytic search should find ~-2.25.
    assert z_min < -1.5


def test_bezpath_bbox_circle():
    # Approximate unit circle with 4 cubics (standard k=0.5523 offset).
    k = 0.5522847498
    bez = [
        (1, 0), (1, k), (k, 1), (0, 1),
        (-k, 1), (-1, k), (-1, 0),
        (-1, -k), (-k, -1), (0, -1),
        (k, -1), (1, -k), (1, 0),
    ]
    (xmin, ymin), (xmax, ymax) = bezpath_bbox(bez)
    assert xmin == pytest.approx(-1.0, abs=1e-3)
    assert xmax == pytest.approx(1.0, abs=1e-3)
    assert ymin == pytest.approx(-1.0, abs=1e-3)
    assert ymax == pytest.approx(1.0, abs=1e-3)


def test_bezpath_radius_at_z_circle():
    # Same unit circle.  At z=0 it must hit r = ±1 (max = 1).
    k = 0.5522847498
    bez = [
        (1, 0), (1, k), (k, 1), (0, 1),
        (-k, 1), (-1, k), (-1, 0),
        (-1, -k), (-k, -1), (0, -1),
        (k, -1), (1, -k), (1, 0),
    ]
    r = bezpath_radius_at_z(bez, 0.0)
    assert r == pytest.approx(1.0, abs=1e-3)
    r_half = bezpath_radius_at_z(bez, 0.5)
    assert r_half == pytest.approx(math.sqrt(1 - 0.25), abs=1e-3)


def test_bezpath_radius_at_z_no_crossing():
    bez = _line_bez((1, 0), (1, 10))
    assert bezpath_radius_at_z(bez, 100.0) is None


def test_bezpath_min_max_axis():
    bez = list(_line_bez((0, 0), (5, 7)))
    p_min_z = bezpath_min_axis(bez, 1)
    p_max_z = bezpath_max_axis(bez, 1)
    assert p_min_z == pytest.approx((0, 0))
    assert p_max_z == pytest.approx((5, 7))


def test_detect_foot_concavity_present():
    # Outer-side of a foot-ring mug.  Walks rim → outer wall → around
    # foot ring outer/bottom/inner → across underside to axis.
    # r_foot = 3 (foot ring outer radius); the under-cut dips to r=1.
    segs = []
    segs += _line_bez((3, 10), (3, 0.5))[:]    # outer wall to foot-top
    segs += _line_bez((3, 0.5), (3, 0))[1:]    # foot-ring outer face
    segs += _line_bez((3, 0), (1, 0))[1:]      # foot-ring bottom
    segs += _line_bez((1, 0), (1, 0.5))[1:]    # foot-ring inner face
    segs += _line_bez((1, 0.5), (0, 0.5))[1:]  # underside to axis
    res = detect_foot_concavity_bez(segs)
    assert res is not None
    z_top, r_foot = res
    assert r_foot == pytest.approx(3.0, abs=1e-3)
    assert z_top == pytest.approx(0.5, abs=0.05)


def test_detect_foot_concavity_absent():
    # Plain straight wall down to axis — no concavity.
    bez = []
    bez += _line_bez((3, 10), (3, 0))[:]
    bez += _line_bez((3, 0), (0, 0))[1:]
    assert detect_foot_concavity_bez(bez) is None


def test_split_outer_bez_at_rim_simple():
    # Closed cylinder: rim at z=10, axis at z=0.  outer side = right wall.
    bez = []
    bez += _line_bez((3, 10), (3, 0))[:]      # outer wall
    bez += _line_bez((3, 0), (0, 0))[1:]      # foot
    bez += _line_bez((0, 0), (0, 10))[1:]     # axis (inner)
    bez += _line_bez((0, 10), (3, 10))[1:]    # rim closing back
    outer = split_outer_bez_at_rim(bez)
    # Outer must start at the rim (max-z knot, r=3) and end near r=0.
    assert outer[0] == pytest.approx((3, 10))
    assert outer[-1][0] < 0.1
