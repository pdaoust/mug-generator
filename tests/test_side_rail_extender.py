"""Tests for side_rail_extender.py."""

import math

import pytest

from lib.rail_sampler import Station
from lib.side_rail_extender import apply_side_rails, penetration_depth, extend_rails_into_body


def _make_station(frac: float, sz: float = 0.0) -> Station:
    return Station(
        centroid=(50.0, 0.0, frac * 100),
        x_axis=(1.0, 0.0, 0.0),
        y_axis=(0.0, 0.0, 1.0),
        z_axis=(0.0, 1.0, 0.0),
        sx=10.0,
        sz=sz,
        arc_length_fraction=frac,
    )


class TestApplySideRails:
    def test_interpolates_sz(self):
        stations = [_make_station(0.0), _make_station(0.5), _make_station(1.0)]
        left = [(2.0, 0.0), (6.0, 1.0)]
        right = [(2.0, 0.0), (6.0, 1.0)]

        result = apply_side_rails(stations, left, right)
        mid = [s for s in result if abs(s.arc_length_fraction - 0.5) < 0.01][0]
        assert mid.sz == pytest.approx(4.0)

    def test_constant_width(self):
        stations = [_make_station(f / 4) for f in range(5)]
        left = [(5.0, 0.0), (5.0, 1.0)]
        right = [(5.0, 0.0), (5.0, 1.0)]

        result = apply_side_rails(stations, left, right)
        for s in result:
            assert s.sz == pytest.approx(5.0, abs=0.1)

    def test_side_rail_y_normalization(self):
        """Side rail Y values at arbitrary scale get normalized to [0,1]."""
        stations = [_make_station(0.0), _make_station(0.5), _make_station(1.0)]
        left = [(3.0, 50), (6.0, 100), (3.0, 150)]
        right = [(3.0, 50), (6.0, 100), (3.0, 150)]

        result = apply_side_rails(stations, left, right)
        mid = [s for s in result if abs(s.arc_length_fraction - 0.5) < 0.01][0]
        assert mid.sz == pytest.approx(6.0)


class TestPenetrationDepth:
    def test_zero_width(self):
        assert penetration_depth(40.0, 0.0) == pytest.approx(0.0)

    def test_small_width(self):
        # R=40, w=5: depth = 40 - sqrt(40²-5²) = 40 - sqrt(1575) ≈ 0.314
        d = penetration_depth(40.0, 5.0)
        expected = 40.0 - math.sqrt(40.0**2 - 5.0**2)
        assert d == pytest.approx(expected)

    def test_half_radius(self):
        # R=40, w=20: depth = 40 - sqrt(1200) = 40 - 34.641 ≈ 5.359
        d = penetration_depth(40.0, 20.0)
        expected = 40.0 - math.sqrt(40.0**2 - 20.0**2)
        assert d == pytest.approx(expected)

    def test_trig_identity(self):
        # Verify R·(1 - cos(arcsin(w/R))) matches
        R, w = 50.0, 10.0
        d = penetration_depth(R, w)
        expected = R * (1 - math.cos(math.asin(w / R)))
        assert d == pytest.approx(expected)

    def test_width_exceeds_radius(self):
        # Handle wider than mug — clamp to full radius
        assert penetration_depth(30.0, 50.0) == pytest.approx(30.0)

    def test_zero_radius(self):
        assert penetration_depth(0.0, 5.0) == 0.0


class TestExtendRailsIntoBody:
    def test_extends_both_ends(self):
        inner = [(40.0, 0.0), (45.0, 50.0), (40.0, 100.0)]
        outer = [(50.0, 0.0), (55.0, 50.0), (50.0, 100.0)]
        left = [(5.0, 0.0), (5.0, 100.0)]
        right = [(5.0, 0.0), (5.0, 100.0)]

        # Mug radius = 40 at all Z
        def mug_r(z):
            return 40.0

        inner_ext, outer_ext = extend_rails_into_body(
            inner, outer, left, right, mug_r
        )

        # Should have 2 extra points per rail (one at each end)
        assert len(inner_ext) == len(inner) + 2
        assert len(outer_ext) == len(outer) + 2

        # Extension points should have same Z as endpoints, lower X
        expected_depth = penetration_depth(40.0, 5.0)
        assert inner_ext[0][0] == pytest.approx(40.0 - expected_depth)
        assert inner_ext[0][1] == pytest.approx(0.0)
        assert inner_ext[-1][0] == pytest.approx(40.0 - expected_depth)
        assert inner_ext[-1][1] == pytest.approx(100.0)

    def test_no_extension_without_radius(self):
        inner = [(40.0, 0.0), (40.0, 100.0)]
        outer = [(50.0, 0.0), (50.0, 100.0)]
        left = [(5.0, 0.0), (5.0, 100.0)]
        right = [(5.0, 0.0), (5.0, 100.0)]

        inner_ext, outer_ext = extend_rails_into_body(
            inner, outer, left, right, None
        )
        assert len(inner_ext) == len(inner)
        assert len(outer_ext) == len(outer)
