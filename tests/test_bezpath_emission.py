"""Tests for _path_d_to_bezpath and get_layer_paths_bez."""

import math

import pytest

from lib.svg_layers import _path_d_to_bezpath, _line_to_bezier


def _bezier_eval(p0, p1, p2, p3, u):
    """Evaluate a cubic Bezier at parameter u."""
    one = 1 - u
    return (
        one**3 * p0[0] + 3 * one**2 * u * p1[0]
        + 3 * one * u**2 * p2[0] + u**3 * p3[0],
        one**3 * p0[1] + 3 * one**2 * u * p1[1]
        + 3 * one * u**2 * p2[1] + u**3 * p3[1],
    )


def _segments(bez):
    """Yield (k0, c1, c2, k1) tuples from a cubic bezpath."""
    for i in range(0, len(bez) - 1, 3):
        yield bez[i], bez[i + 1], bez[i + 2], bez[i + 3]


class TestLineToBezier:
    def test_handles_at_thirds(self):
        c1, c2, k1 = _line_to_bezier((0, 0), (9, 3))
        assert c1 == pytest.approx((3, 1))
        assert c2 == pytest.approx((6, 2))
        assert k1 == pytest.approx((9, 3))

    def test_evaluates_to_chord(self):
        # A 1/3-2/3-handle Bezier should sample a straight line.
        p0, p1 = (1, 2), (10, 5)
        c1, c2, k1 = _line_to_bezier(p0, p1)
        for u in [0.0, 0.25, 0.5, 0.75, 1.0]:
            x, y = _bezier_eval(p0, c1, c2, k1, u)
            assert x == pytest.approx(p0[0] + u * (p1[0] - p0[0]))
            assert y == pytest.approx(p0[1] + u * (p1[1] - p0[1]))


class TestParseLinearPath:
    def test_simple_line(self):
        bez, closed = _path_d_to_bezpath("M 0 0 L 10 0")
        assert closed is False
        assert len(bez) == 4  # k0, c1, c2, k1
        assert bez[0] == (0.0, 0.0)
        assert bez[3] == (10.0, 0.0)

    def test_horizontal_and_vertical(self):
        bez, closed = _path_d_to_bezpath("M 0 0 H 10 V 5")
        assert closed is False
        # Two segments → 1 + 2*3 = 7 points
        assert len(bez) == 7
        assert bez[0] == (0.0, 0.0)
        assert bez[3] == (10.0, 0.0)
        assert bez[6] == (10.0, 5.0)

    def test_closed_rectangle(self):
        bez, closed = _path_d_to_bezpath("M 0 0 H 10 V 5 H 0 Z")
        assert closed is True
        # 3 explicit segments + 1 closing segment = 4 segments
        assert len(bez) == 13  # 1 + 4*3
        assert bez[0] == (0.0, 0.0)
        assert bez[-1] == (0.0, 0.0)


class TestParseCubic:
    def test_single_cubic_passthrough(self):
        d = "M 0 0 C 5 35 60 -25 80 0"
        bez, closed = _path_d_to_bezpath(d)
        assert closed is False
        assert len(bez) == 4
        assert bez == [(0, 0), (5, 35), (60, -25), (80, 0)]

    def test_smooth_cubic_reflects_control(self):
        # M 0 0 C 1 1 2 1 3 0 → after C, last_c2 = (2,1).
        # S 5 -1 6 0 → reflected c1 = (4, -1), c2 = (5, -1), end = (6, 0).
        bez, closed = _path_d_to_bezpath("M 0 0 C 1 1 2 1 3 0 S 5 -1 6 0")
        assert closed is False
        assert len(bez) == 7  # 2 cubic segments
        assert bez[3] == (3, 0)  # shared knot
        assert bez[4] == (4, -1)  # reflected control
        assert bez[5] == (5, -1)
        assert bez[6] == (6, 0)


class TestParseQuadratic:
    def test_quadratic_to_cubic(self):
        # Q (1, 2) (3, 0) from (0,0):
        # cp1 = (0 + 2/3*1, 0 + 2/3*2) = (2/3, 4/3)
        # cp2 = (3 + 2/3*(1-3), 0 + 2/3*(2-0)) = (3 - 4/3, 4/3) = (5/3, 4/3)
        bez, closed = _path_d_to_bezpath("M 0 0 Q 1 2 3 0")
        assert closed is False
        assert len(bez) == 4
        assert bez[1] == pytest.approx((2/3, 4/3))
        assert bez[2] == pytest.approx((5/3, 4/3))
        assert bez[3] == (3, 0)


class TestParseRelativeCommands:
    def test_lowercase_l_is_relative(self):
        bez, _ = _path_d_to_bezpath("M 1 1 l 2 3")
        assert bez[0] == (1, 1)
        assert bez[3] == (3, 4)

    def test_lowercase_c_is_relative(self):
        bez, _ = _path_d_to_bezpath("M 10 20 c 1 2 3 4 5 6")
        assert bez[0] == (10, 20)
        assert bez[1] == (11, 22)
        assert bez[2] == (13, 24)
        assert bez[3] == (15, 26)


class TestBezpathStructure:
    """Bezpath must satisfy len == 1 + 3*n_segments."""

    def test_line_bezpath_modulo(self):
        bez, _ = _path_d_to_bezpath("M 0 0 L 1 0 L 2 0 L 3 0")
        assert (len(bez) - 1) % 3 == 0
        assert (len(bez) - 1) // 3 == 3

    def test_mixed_bezpath_modulo(self):
        bez, _ = _path_d_to_bezpath("M 0 0 L 1 0 C 2 1 3 1 4 0 H 5 V 1")
        assert (len(bez) - 1) % 3 == 0
        # 4 segments: L, C, H, V
        assert (len(bez) - 1) // 3 == 4
