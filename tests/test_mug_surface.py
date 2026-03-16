"""Tests for mug_surface.py."""

import pytest

from lib.mug_surface import MugSurface


class TestMugSurface:
    def test_axis_at_origin(self):
        # Axis is always at x=0 (document origin); X values are radii directly
        surface = MugSurface([[10, 0], [15, 50], [20, 100]])
        assert surface.axis_x == 0.0
        assert surface.profile[0][0] == pytest.approx(10.0)
        assert surface.profile[1][0] == pytest.approx(15.0)
        assert surface.profile[2][0] == pytest.approx(20.0)

    def test_sorted_by_z(self):
        surface = MugSurface([[10, 100], [15, 0], [20, 50]])
        zs = [p[1] for p in surface.profile]
        assert zs == sorted(zs)

    def test_radius_at_z_interpolation(self):
        # Straight line from (radius=5, z=0) to (radius=15, z=100)
        surface = MugSurface([[5, 0], [15, 100]])
        assert surface.radius_at_z(50) == pytest.approx(10.0)
        assert surface.radius_at_z(0) == pytest.approx(5.0)
        assert surface.radius_at_z(100) == pytest.approx(15.0)

    def test_radius_at_z_outside_range(self):
        surface = MugSurface([[5, 0], [15, 100]])
        assert surface.radius_at_z(-10) is None
        assert surface.radius_at_z(110) is None

    def test_z_min_max(self):
        surface = MugSurface([[5, 10], [15, 90]])
        assert surface.z_min == pytest.approx(10.0)
        assert surface.z_max == pytest.approx(90.0)

    def test_negative_radius_raises(self):
        # Points left of the document origin (x < 0) are invalid
        with pytest.raises(ValueError, match="negative radius"):
            MugSurface([[-1, 0], [5, 100]])

    def test_too_few_points(self):
        with pytest.raises(ValueError, match="at least 2"):
            MugSurface([[10, 0]])

    def test_multi_segment_interpolation(self):
        # Three segments: x values are radii directly
        surface = MugSurface([[0, 0], [10, 50], [5, 100]])
        assert surface.radius_at_z(25) == pytest.approx(5.0)
        assert surface.radius_at_z(75) == pytest.approx(7.5)
