"""Tests for profile_transformer.py."""

import math

import pytest

from lib.profile_transformer import normalize_profile, transform_profile_at_station, generate_handle_stations
from lib.rail_sampler import Station


class TestNormalizeProfile:
    def test_unit_square(self):
        profile = [(0, 0), (10, 0), (10, 10), (0, 10)]
        norm = normalize_profile(profile)
        assert len(norm) == 4

        xs = [p[0] for p in norm]
        ys = [p[1] for p in norm]
        assert min(xs) == pytest.approx(-0.5)
        assert max(xs) == pytest.approx(0.5)
        assert min(ys) == pytest.approx(-0.5)
        assert max(ys) == pytest.approx(0.5)

    def test_ccw_enforcement(self):
        # CW square
        profile = [(0, 0), (0, 10), (10, 10), (10, 0)]
        norm = normalize_profile(profile)
        # Check CCW by shoelace
        area = 0
        n = len(norm)
        for i in range(n):
            j = (i + 1) % n
            area += norm[i][0] * norm[j][1] - norm[j][0] * norm[i][1]
        assert area > 0  # CCW = positive

    def test_rectangular_profile_independent_axes(self):
        """Non-square rectangle: each axis normalized independently to [-0.5, 0.5]."""
        profile = [(0, 0), (20, 0), (20, 10), (0, 10)]
        norm = normalize_profile(profile)
        xs = [p[0] for p in norm]
        ys = [p[1] for p in norm]
        # Both axes should span [-0.5, 0.5]
        assert min(xs) == pytest.approx(-0.5)
        assert max(xs) == pytest.approx(0.5)
        assert min(ys) == pytest.approx(-0.5)
        assert max(ys) == pytest.approx(0.5)

    def test_too_few_points(self):
        with pytest.raises(ValueError, match="at least 3"):
            normalize_profile([(0, 0), (1, 0)])


class TestTransformProfileAtStation:
    def test_identity_transform(self):
        """Profile at origin with unit frame and scale=1."""
        profile = [(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)]
        station = Station(
            centroid=(100, 0, 50),
            x_axis=(1, 0, 0),
            y_axis=(0, 0, 1),
            z_axis=(0, 1, 0),
            sx=1.0,
            sz=1.0,
            arc_length_fraction=0.5,
        )
        pts3d = transform_profile_at_station(profile, station)
        assert len(pts3d) == 4
        # Center should be at centroid
        cx = sum(p[0] for p in pts3d) / 4
        cy = sum(p[1] for p in pts3d) / 4
        cz = sum(p[2] for p in pts3d) / 4
        assert cx == pytest.approx(100.0)
        assert cy == pytest.approx(0.0)
        assert cz == pytest.approx(50.0)

    def test_axis_mapping(self):
        """Profile u (X) maps to z_axis/sz, profile v (Y) maps to x_axis/sx."""
        # Profile wide in u, narrow in v
        profile = [(-0.5, 0), (0.5, 0), (0, 0.25)]
        station = Station(
            centroid=(0, 0, 0),
            x_axis=(1, 0, 0),   # inner-outer direction
            y_axis=(0, 0, 1),   # forward
            z_axis=(0, 1, 0),   # protrusion direction
            sx=20.0,            # inner-outer scale
            sz=10.0,            # protrusion scale (side rails)
            arc_length_fraction=0.5,
        )
        pts3d = transform_profile_at_station(profile, station)
        # u=[-0.5, 0.5] * sz=10 → y range should be 10
        ys = [p[1] for p in pts3d]
        assert max(ys) - min(ys) == pytest.approx(10.0)
        # v=[0, 0.25] * sx=20 → x range should be 5
        xs = [p[0] for p in pts3d]
        assert max(xs) - min(xs) == pytest.approx(5.0)


class TestGenerateHandleStations:
    def test_generates_correct_count(self):
        profile = [(0, 0), (10, 0), (10, 10), (0, 10)]
        stations = [
            Station(
                centroid=(50, 0, i * 10),
                x_axis=(1, 0, 0),
                y_axis=(0, 0, 1),
                z_axis=(0, 1, 0),
                sx=10.0,
                sz=5.0,
                arc_length_fraction=i / 4,
            )
            for i in range(5)
        ]
        result = generate_handle_stations(profile, stations)
        assert len(result) == 5
        assert all(len(poly) == 4 for poly in result)
