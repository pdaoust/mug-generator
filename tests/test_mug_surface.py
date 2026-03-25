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


class TestFootConcavity:
    def test_no_concavity_straight(self):
        surface = MugSurface([[30, 0], [30, 100]])
        assert surface.detect_foot_concavity() is None

    def test_no_concavity_widening(self):
        # Foot gets wider going up — no concavity
        surface = MugSurface([[25, 0], [30, 10], [35, 100]])
        assert surface.detect_foot_concavity() is None

    def test_foot_ring_detected(self):
        # Foot ring: radius 30 at z=0, tucks to 25 at z=3, back to 30 at z=6
        surface = MugSurface([[30, 0], [25, 3], [30, 6], [35, 100]])
        result = surface.detect_foot_concavity()
        assert result is not None
        z, r = result
        assert r == pytest.approx(30.0)
        assert z == pytest.approx(6.0)

    def test_subtle_concavity(self):
        surface = MugSurface([[30, 0], [29.5, 2], [30, 4], [32, 100]])
        result = surface.detect_foot_concavity()
        assert result is not None
        z, r = result
        assert z == pytest.approx(4.0)

    def test_interpolated_crossing(self):
        # Crossing happens between profile points
        surface = MugSurface([[30, 0], [26, 3], [34, 7], [34, 100]])
        result = surface.detect_foot_concavity()
        assert result is not None
        z, r = result
        # Linear interp: r goes from 26→34 over z 3→7, crosses 30 at z=5
        assert z == pytest.approx(5.0)
        assert r == pytest.approx(30.0)

    def test_noise_near_foot_bottom(self):
        # SVG sampling noise: tiny dip near the foot bottom resolves
        # immediately, but the real concavity is deeper and resolves later.
        # Profile: foot at r=30 z=0, noise dip to 29.99 at z=0.01,
        # back to 30 at z=0.02, then real concavity to 25 at z=1.5,
        # resolves at z=3.
        surface = MugSurface([
            [30, 0], [29.99, 0.01], [30, 0.02],
            [27, 0.5], [25, 1.5], [27, 2.5], [30, 3], [35, 100],
        ])
        result = surface.detect_foot_concavity()
        assert result is not None
        z, r = result
        # Should find the real crossing at z=3, not the noise at z=0.02
        assert z == pytest.approx(3.0)
        assert r == pytest.approx(30.0)
