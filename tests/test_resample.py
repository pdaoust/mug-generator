"""Tests for polyline simplification (merge-only, corner-preserving)."""

import math

import pytest

from lib.resample import resample_polyline


class TestResampleOpen:
    def test_straight_line_unchanged(self):
        """A two-point straight segment is never modified."""
        pts = [(0, 0), (100, 0)]
        result = resample_polyline(pts, 2.0)
        assert result == [(0, 0), (100, 0)]

    def test_polyline_straight_segments_preserved(self):
        """Connected straight segments with corners are kept as-is."""
        pts = [(0, 0), (10, 0), (10, 10), (0, 10)]
        result = resample_polyline(pts, 2.0)
        assert len(result) == 4
        for a, b in zip(result, pts):
            assert a == pytest.approx(b)

    def test_dense_curve_simplified(self):
        """A densely sampled arc is simplified to fewer points."""
        n = 64
        r = 20.0
        # Quarter circle (90°) — 64 segments, each ~0.5mm
        pts = [(r * math.cos(math.pi / 2 * i / n),
                r * math.sin(math.pi / 2 * i / n)) for i in range(n + 1)]
        result = resample_polyline(pts, 5.0)
        assert len(result) < n // 2  # significantly fewer points
        assert len(result) >= 4      # but not degenerate
        # Endpoints preserved
        assert result[0] == pytest.approx(pts[0])
        assert result[-1] == pytest.approx(pts[-1])

    def test_straight_then_curve_preserves_straight(self):
        """A straight segment followed by a curve: straight unchanged,
        curve simplified."""
        straight = [(0, 0), (30, 0)]  # 30mm straight line
        # Arc from (30,0), curving upward — 32 tiny segments
        n = 32
        r = 10.0
        curve = [(30 + r * math.sin(math.pi / 2 * i / n),
                  r * (1 - math.cos(math.pi / 2 * i / n))) for i in range(1, n + 1)]
        pts = straight + curve

        result = resample_polyline(pts, 3.0)
        # Straight segment preserved (first two points)
        assert result[0] == pytest.approx((0, 0))
        assert result[1] == pytest.approx((30, 0))
        # Curve section has fewer points than original 32
        curve_pts = result[2:]
        assert len(curve_pts) < 20

    def test_corners_preserved(self):
        """Points with angular deviation ≥ 15° are always kept."""
        # Right angle corner at (10, 0)
        pts = [(0, 0), (5, 0), (10, 0), (10, 5), (10, 10)]
        result = resample_polyline(pts, 100.0)
        # Corner at (10, 0) must be kept despite large max_seg_len
        assert any(abs(p[0] - 10) < 1e-9 and abs(p[1]) < 1e-9
                   for p in result)

    def test_endpoints_always_kept(self):
        n = 32
        pts = [(i * 0.1, math.sin(i * 0.1)) for i in range(n)]
        result = resample_polyline(pts, 5.0)
        assert result[0] == pytest.approx(pts[0])
        assert result[-1] == pytest.approx(pts[-1])

    def test_too_few_points_passthrough(self):
        assert resample_polyline([(0, 0)], 1.0) == [(0, 0)]
        assert resample_polyline([(0, 0), (1, 0)], 1.0) == [(0, 0), (1, 0)]

    def test_zero_target_passthrough(self):
        pts = [(0, 0), (1, 0), (2, 0)]
        assert resample_polyline(pts, 0) == list(pts)


class TestResampleClosed:
    def test_circle_simplified(self):
        """A densely sampled circle is simplified."""
        n = 64
        r = 10.0
        pts = [(r * math.cos(2 * math.pi * i / n),
                r * math.sin(2 * math.pi * i / n)) for i in range(n)]
        result = resample_polyline(pts, 3.0, closed=True)
        assert len(result) < n // 2
        assert len(result) >= 6
        # No closing duplicate
        dist = math.hypot(result[-1][0] - result[0][0],
                          result[-1][1] - result[0][1])
        assert dist > 1.0
        # All points still approximately on the circle
        for p in result:
            assert math.hypot(p[0], p[1]) == pytest.approx(r, abs=0.5)

    def test_square_unchanged(self):
        """A square (all corners) is unchanged."""
        pts = [(0, 0), (10, 0), (10, 10), (0, 10)]
        result = resample_polyline(pts, 2.0, closed=True)
        assert len(result) == 4
        for a, b in zip(result, pts):
            assert a == pytest.approx(b)

    def test_rounded_rect_preserves_corners(self):
        """A rounded rectangle: straight sides kept, rounded corners
        simplified, but the 4 main corners preserved."""
        pts = []
        # Bottom side: straight
        pts.extend([(0, 0), (10, 0)])
        # Bottom-right corner: quarter circle r=2
        n = 16
        for i in range(1, n):
            t = math.pi / 2 * i / n
            pts.append((10 + 2 * math.sin(t), 2 * (1 - math.cos(t))))
        # Right side: straight
        pts.extend([(12, 2), (12, 8)])
        # Top-right corner
        for i in range(1, n):
            t = math.pi / 2 * i / n
            pts.append((12 - 2 * (1 - math.cos(t)), 8 + 2 * math.sin(t)))
        # Top side
        pts.extend([(10, 10), (0, 10)])
        # Top-left corner
        for i in range(1, n):
            t = math.pi / 2 * i / n
            pts.append((-2 * math.sin(t), 10 - 2 * (1 - math.cos(t))))
        # Left side
        pts.extend([(-2, 8), (-2, 2)])
        # Bottom-left corner
        for i in range(1, n):
            t = math.pi / 2 * i / n
            pts.append((-2 + 2 * (1 - math.cos(t)), 2 * math.sin(t)))

        result = resample_polyline(pts, 2.0, closed=True)
        # Should have fewer points than original (corners simplified)
        assert len(result) < len(pts)
        # But the 4 sharp transition points should still be there
        assert len(result) >= 8  # at least corners + midpoints
