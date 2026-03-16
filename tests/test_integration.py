"""Integration test: full pipeline from SVG to .scad output."""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from lib.svg_layers import get_layer_paths
from lib.units import to_mm, parse_doc_units, parse_viewbox_scale
from lib.mug_surface import MugSurface
from lib.openscad_params import compute_n
from lib.rail_sampler import sample_rails, _cumulative_chord_lengths, _build_midpoint_curve
from lib.side_rail_extender import apply_side_rails
from lib.profile_transformer import generate_handle_stations
from lib.scad_writer import run_all_emitters


FIXTURE_SVG = Path(__file__).parent / "fixtures" / "sample.svg"


def _parse_scad_array(text: str, var_name: str):
    pattern = rf'{var_name}\s*=\s*(\[[\s\S]*?\]);\s*$'
    match = re.search(pattern, text, re.MULTILINE)
    assert match, f"Could not find '{var_name}'"
    return eval(match.group(1))  # noqa: S307


def _run_pipeline(svg_path: Path, output_dir: Path, fn=0, fa=12, fs=2):
    """Run the full pipeline without inkex (pure stdlib XML parsing)."""
    tree = ET.parse(svg_path)
    svg_root = tree.getroot()

    doc_units = parse_doc_units(svg_root)
    scale = parse_viewbox_scale(svg_root, doc_units)

    def svg_to_mm(points):
        return [
            (to_mm(p[0] * scale, doc_units), to_mm(-p[1] * scale, doc_units))
            for p in points
        ]

    mug_body_paths = get_layer_paths(svg_root, "mug body")
    handle_rail_paths = get_layer_paths(svg_root, "handle rails")
    side_rail_paths = get_layer_paths(svg_root, "side rails")
    profile_paths = get_layer_paths(svg_root, "handle profile")

    mug_outer_mm = svg_to_mm(mug_body_paths[0])
    mug_inner_mm = svg_to_mm(mug_body_paths[1])
    inner_rail_mm = svg_to_mm(handle_rail_paths[0])
    outer_rail_mm = svg_to_mm(handle_rail_paths[1])

    left_side = [(to_mm(p[0] * scale, doc_units), to_mm(p[1] * scale, doc_units))
                 for p in side_rail_paths[0]]
    right_side = [(to_mm(p[0] * scale, doc_units), to_mm(p[1] * scale, doc_units))
                  for p in side_rail_paths[1]]

    handle_profile = [(p[0], p[1]) for p in profile_paths[0]]

    mug_surface = MugSurface([[p[0], p[1]] for p in mug_outer_mm])

    def mug_true_radius_at_z(z):
        return mug_surface.radius_at_z(z)

    midpoints = _build_midpoint_curve(inner_rail_mm, outer_rail_mm)
    mid_cl = _cumulative_chord_lengths(midpoints)
    mid_total = mid_cl[-1]

    n_stations = compute_n(fn, fa, fs, mid_total)
    n_stations = max(n_stations, 5)

    stations = sample_rails(inner_rail_mm, outer_rail_mm, n_stations)
    stations = apply_side_rails(stations, left_side, right_side)

    handle_stations_3d = generate_handle_stations(
        handle_profile, stations,
        mug_axis_x=mug_surface.axis_x,
        mug_radius_at_z=mug_true_radius_at_z,
    )

    # Raw polygon vertices in path order, axis offset subtracted
    axis_x = mug_surface.axis_x
    scad_outer_profile = [[p[0] - axis_x, p[1]] for p in mug_outer_mm]
    scad_inner_profile = [[p[0] - axis_x, p[1]] for p in mug_inner_mm]

    data = {
        "mug_outer_profile": scad_outer_profile,
        "mug_inner_profile": scad_inner_profile,
        "handle_stations": [
            [list(pt) for pt in poly] for poly in handle_stations_3d
        ],
        "handle_path": [list(s.centroid) for s in stations],
        "mug_params": {
            "fn": fn,
            "fa": fa,
            "fs": fs,
            "axis_x": mug_surface.axis_x,
        },
    }

    run_all_emitters(data, output_dir)
    return data


class TestIntegration:
    def test_full_pipeline(self, tmp_path):
        """Run full pipeline and verify output files exist and parse correctly."""
        data = _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)

        assert (tmp_path / "mug_outer_profile.scad").exists()
        assert (tmp_path / "mug_inner_profile.scad").exists()
        assert (tmp_path / "handle_stations.scad").exists()
        assert (tmp_path / "handle_path.scad").exists()
        assert (tmp_path / "mug_params.scad").exists()
        assert (tmp_path / "mug.scad").exists()

    def test_mug_profiles_valid(self, tmp_path):
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)

        outer_text = (tmp_path / "mug_outer_profile.scad").read_text()
        outer = _parse_scad_array(outer_text, "mug_outer_profile")
        assert len(outer) >= 2
        for pt in outer:
            assert pt[0] >= -0.01, f"Negative radius in outer: {pt}"

        inner_text = (tmp_path / "mug_inner_profile.scad").read_text()
        inner = _parse_scad_array(inner_text, "mug_inner_profile")
        assert len(inner) >= 2
        for pt in inner:
            assert pt[0] >= -0.01, f"Negative radius in inner: {pt}"

    def test_handle_stations_valid(self, tmp_path):
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)
        text = (tmp_path / "handle_stations.scad").read_text()
        stations = _parse_scad_array(text, "handle_stations")

        assert len(stations) >= 5
        n_pts = len(stations[0])
        assert n_pts >= 3
        for s in stations:
            assert len(s) == n_pts

    def test_handle_path_valid(self, tmp_path):
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)
        text = (tmp_path / "handle_path.scad").read_text()
        path = _parse_scad_array(text, "handle_path")

        assert len(path) >= 5
        for pt in path:
            assert len(pt) == 3

    def test_params_written(self, tmp_path):
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)
        text = (tmp_path / "mug_params.scad").read_text()
        assert "$fn = 20" in text
        assert "mug_axis_x" in text

    def test_numeric_consistency(self, tmp_path):
        """Run pipeline twice and verify outputs match within tolerance."""
        data1 = _run_pipeline(FIXTURE_SVG, tmp_path / "run1", fn=20)
        data2 = _run_pipeline(FIXTURE_SVG, tmp_path / "run2", fn=20)

        for p1, p2 in zip(data1["mug_outer_profile"], data2["mug_outer_profile"]):
            assert p1 == pytest.approx(p2, abs=1e-6)

        for s1, s2 in zip(data1["handle_stations"], data2["handle_stations"]):
            for p1, p2 in zip(s1, s2):
                assert p1 == pytest.approx(p2, abs=1e-6)

    def test_auto_resolution(self, tmp_path):
        """Test with auto resolution (fn=0) — should still produce valid output."""
        data = _run_pipeline(FIXTURE_SVG, tmp_path, fn=0, fa=12, fs=2)
        assert len(data["handle_stations"]) >= 5
