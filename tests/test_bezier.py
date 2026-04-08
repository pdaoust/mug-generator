"""Tests for adaptive Bezier subdivision."""

import math

from lib.svg_layers import _de_casteljau, _parse_path_d


class TestAdaptiveSubdivision:
    """Tests for _de_casteljau adaptive flattening."""

    def test_straight_line_produces_two_points(self):
        result = _de_casteljau((0, 0), (1, 0), (2, 0), (3, 0))
        assert len(result) == 2
        assert result[0] == (0, 0)
        assert result[-1] == (3, 0)

    def test_endpoints_preserved(self):
        result = _de_casteljau((1, 2), (3, 8), (7, 5), (10, 1), fa_deg=1)
        assert result[0] == (1, 2)
        assert result[-1] == (10, 1)

    def test_degenerate_zero_length_curve(self):
        result = _de_casteljau((5, 5), (5, 5), (5, 5), (5, 5))
        assert len(result) == 2
        assert result[0] == (5, 5)
        assert result[-1] == (5, 5)

    def test_quarter_circle_within_tolerance(self):
        # Standard cubic approximation to a quarter circle
        k = 0.5522847498
        result = _de_casteljau((1, 0), (1, k), (k, 1), (0, 1), fa_deg=2)
        assert len(result) >= 3  # should produce multiple segments
        for x, y in result:
            dist_from_origin = math.hypot(x, y)
            assert abs(dist_from_origin - 1.0) < 0.02  # within tolerance of unit circle

    def test_cusp_does_not_collapse(self):
        # P0 ≈ P3 but control points are far away
        result = _de_casteljau((0, 0), (10, 10), (-10, 10), (0, 0), fa_deg=5)
        assert len(result) > 2

    def test_fa_controls_density(self):
        p0, p1, p2, p3 = (0, 0), (1, 5), (5, 5), (6, 0)
        coarse = _de_casteljau(p0, p1, p2, p3, fa_deg=30)
        fine = _de_casteljau(p0, p1, p2, p3, fa_deg=1)
        assert len(fine) > len(coarse)

    def test_fs_prevents_over_subdivision(self):
        # With a very fine fa but a coarse fs, fs should limit density
        p0, p1, p2, p3 = (0, 0), (1, 5), (5, 5), (6, 0)
        fine_fa_only = _de_casteljau(p0, p1, p2, p3, fa_deg=0.1)
        fine_fa_coarse_fs = _de_casteljau(p0, p1, p2, p3, fa_deg=0.1, fs=3.0)
        assert len(fine_fa_coarse_fs) < len(fine_fa_only)

    def test_fn_derived_fa(self):
        # Simulate $fn=36 → fa=10 degrees, no fs
        p0, p1, p2, p3 = (0, 0), (1, 5), (5, 5), (6, 0)
        result = _de_casteljau(p0, p1, p2, p3, fa_deg=360.0 / 36)
        assert len(result) >= 2
        assert result[0] == p0
        assert result[-1] == p3

    def test_near_axis_no_tiny_intermediate_x(self):
        # Bezier from (4.333, 0) to (0, 0) with all control points at origin.
        # This mimics the mug foot profile curve.  Uniform-t sampling would
        # produce intermediate points like x=0.068; adaptive should not.
        result = _de_casteljau((4.333, 0), (0, 0), (0, 0), (0, 0), fa_deg=2)
        for x, y in result[1:-1]:  # skip endpoints
            # No intermediate point should be very close to but not at the axis
            assert x == 0.0 or x > 0.1, (
                f"intermediate point x={x} is a near-axis artifact"
            )

    def test_recursion_terminates(self):
        # A curve that is never flat (control points always off-chord).
        # Should still terminate due to depth limit.
        result = _de_casteljau((0, 0), (0, 100), (100, -100), (100, 0),
                               fa_deg=1e-15)
        assert len(result) <= 4097  # 2^12 + 1

    def test_default_tolerance_without_params(self):
        # Should work without fa_deg/fs, using default tolerance
        result = _de_casteljau((0, 0), (1, 5), (5, 5), (6, 0))
        assert len(result) >= 2
        assert result[0] == (0, 0)
        assert result[-1] == (6, 0)


class TestParsePathWithAdaptiveBezier:
    """Verify _parse_path_d still works correctly with adaptive subdivision."""

    def test_cubic_bezier_path(self):
        result = _parse_path_d("M 0 0 C 1 0.55 0.55 1 0 1")
        assert len(result) >= 2
        assert result[0] == (0.0, 0.0)
        assert abs(result[-1][0]) < 1e-9
        assert abs(result[-1][1] - 1.0) < 1e-9

    def test_relative_cubic_bezier(self):
        result = _parse_path_d("M 10 10 c 1 0.55 0.55 1 0 1")
        assert result[0] == (10.0, 10.0)
        assert abs(result[-1][0] - 10.0) < 1e-9
        assert abs(result[-1][1] - 11.0) < 1e-9

    def test_smooth_cubic(self):
        result = _parse_path_d("M 0 0 C 0 1 1 1 1 0 S 2 -1 2 0")
        assert len(result) >= 3
        assert result[0] == (0.0, 0.0)
        assert abs(result[-1][0] - 2.0) < 1e-9
        assert abs(result[-1][1]) < 1e-9

    def test_quadratic_bezier(self):
        result = _parse_path_d("M 0 0 Q 1 2 2 0")
        assert len(result) >= 2
        assert result[0] == (0.0, 0.0)
        assert abs(result[-1][0] - 2.0) < 1e-9
        assert abs(result[-1][1]) < 1e-9

    def test_fa_fs_threaded_through(self):
        # Verify that fa_deg/fs are passed through to subdivision
        coarse = _parse_path_d("M 0 0 C 0 5 5 5 5 0", fa_deg=30)
        fine = _parse_path_d("M 0 0 C 0 5 5 5 5 0", fa_deg=1)
        assert len(fine) > len(coarse)
