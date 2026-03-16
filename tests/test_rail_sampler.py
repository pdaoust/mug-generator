"""Tests for rail_sampler.py."""

import math

import pytest

from lib.rail_sampler import sample_rails, Station, _cumulative_chord_lengths


class TestCumulativeChordLengths:
    def test_straight_line(self):
        pts = [(0, 0), (3, 4)]
        cl = _cumulative_chord_lengths(pts)
        assert cl == [0.0, 5.0]

    def test_three_points(self):
        pts = [(0, 0), (1, 0), (1, 1)]
        cl = _cumulative_chord_lengths(pts)
        assert cl == pytest.approx([0.0, 1.0, 2.0])


class TestSampleRails:
    def test_straight_parallel_rails(self):
        """Two horizontal parallel rails should give straight handle path."""
        inner = [(0, 0), (100, 0)]  # inner rail: x=0→100, z=0
        outer = [(0, 10), (100, 10)]  # outer rail: x=0→100, z=10

        stations = sample_rails(inner, outer, n_stations=5)
        assert len(stations) == 5

        # Centroids should be at z=5, y=0, x evenly spaced
        for i, s in enumerate(stations):
            expected_x = i * 25.0
            assert s.centroid[0] == pytest.approx(expected_x, abs=0.5)
            assert s.centroid[1] == pytest.approx(0.0)
            assert s.centroid[2] == pytest.approx(5.0, abs=0.5)

        # sx should be ~10 (distance between rails)
        for s in stations:
            assert s.sx == pytest.approx(10.0, abs=0.5)

    def test_arc_length_fractions(self):
        inner = [(0, 0), (100, 0)]
        outer = [(0, 10), (100, 10)]
        stations = sample_rails(inner, outer, n_stations=5)

        fracs = [s.arc_length_fraction for s in stations]
        assert fracs == pytest.approx([0.0, 0.25, 0.5, 0.75, 1.0])

    def test_frame_orthogonality(self):
        """Frame axes should be mutually orthogonal."""
        inner = [(0, 0), (50, 50), (100, 0)]
        outer = [(10, 0), (60, 50), (110, 0)]
        stations = sample_rails(inner, outer, n_stations=10)

        for s in stations:
            # x · y ≈ 0
            dot_xy = sum(a * b for a, b in zip(s.x_axis, s.y_axis))
            assert dot_xy == pytest.approx(0.0, abs=1e-6)
            # x · z ≈ 0
            dot_xz = sum(a * b for a, b in zip(s.x_axis, s.z_axis))
            assert dot_xz == pytest.approx(0.0, abs=1e-6)
            # y · z ≈ 0
            dot_yz = sum(a * b for a, b in zip(s.y_axis, s.z_axis))
            assert dot_yz == pytest.approx(0.0, abs=1e-6)

    def test_minimum_stations(self):
        with pytest.raises(ValueError, match="at least 2"):
            sample_rails([(0, 0), (100, 0)], [(0, 10), (100, 10)], n_stations=1)

    def test_circular_arc_rails(self):
        """Semi-circular rails should produce stations around the arc."""
        n_pts = 50
        inner = []
        outer = []
        for i in range(n_pts + 1):
            angle = math.pi * i / n_pts
            r_in = 40
            r_out = 50
            inner.append((r_in * math.cos(angle), r_in * math.sin(angle)))
            outer.append((r_out * math.cos(angle), r_out * math.sin(angle)))

        stations = sample_rails(inner, outer, n_stations=11)
        assert len(stations) == 11

        # sx should be roughly 10 (r_out - r_in)
        for s in stations:
            assert s.sx == pytest.approx(10.0, abs=1.0)
