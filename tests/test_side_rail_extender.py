"""Tests for side_rail_extender.py."""

import pytest

from lib.rail_sampler import Station
from lib.side_rail_extender import apply_side_rails


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

    def test_symmetric_single_rail(self):
        """Same rail passed for both left and right gives that rail's width."""
        stations = [_make_station(0.0), _make_station(0.5), _make_station(1.0)]
        rail = [(3.0, 0.0), (7.0, 1.0)]

        result = apply_side_rails(stations, rail, rail)
        mid = [s for s in result if abs(s.arc_length_fraction - 0.5) < 0.01][0]
        assert mid.sz == pytest.approx(5.0)
