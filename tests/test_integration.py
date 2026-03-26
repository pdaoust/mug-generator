"""Integration test: full pipeline from SVG to .scad output."""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from lib.svg_layers import get_layer_paths, get_layer_mark_polygons
from lib.units import to_mm, parse_doc_units, parse_viewbox_bottom, parse_viewbox_scale
from lib.mug_surface import MugSurface
from lib.openscad_params import compute_n
from lib.rail_sampler import sample_rails, _cumulative_chord_lengths, _build_midpoint_curve
from lib.side_rail_extender import apply_side_rails
from lib.profile_transformer import generate_handle_stations, normalize_profile
from lib.scad_writer import run_all_emitters
from lib.handle_nudge import nudge_handle_stations
from lib.profile_split import split_body_profile


FIXTURE_SVG = Path(__file__).parent / "fixtures" / "sample.svg"


def _parse_scad_array(text: str, var_name: str):
    pattern = rf'{var_name}\s*=\s*(\[[\s\S]*?\]);\s*$'
    match = re.search(pattern, text, re.MULTILINE)
    assert match, f"Could not find '{var_name}'"
    return eval(match.group(1))  # noqa: S307


def _run_pipeline(svg_path: Path, output_dir: Path, fn=0, fa=12, fs=2,
                   clay_shrinkage=0.0, mark_depth=1.0, mark_inset=True,
                   mark_draft_angle=45.0, mark_layer_height=0.2):
    """Run the full pipeline without inkex (pure stdlib XML parsing)."""
    tree = ET.parse(svg_path)
    svg_root = tree.getroot()

    doc_units = parse_doc_units(svg_root)
    scale = parse_viewbox_scale(svg_root, doc_units)
    vb_bottom = parse_viewbox_bottom(svg_root)

    def svg_to_mm(points):
        return [
            (to_mm(p[0] * scale, doc_units),
             to_mm((vb_bottom - p[1]) * scale, doc_units))
            for p in points
        ]

    mug_body_paths = get_layer_paths(svg_root, "mug body")
    body_mm = svg_to_mm(mug_body_paths[0])
    mug_outer_mm, mug_inner_mm = split_body_profile(body_mm)
    filler_tube_height = 15.0
    rim_z = mug_outer_mm[0][1]
    inner_r = mug_inner_mm[0][0]
    tube_top = rim_z + filler_tube_height
    mug_inner_mm = [(inner_r, tube_top)] + list(mug_inner_mm)

    mug_surface = MugSurface([[p[0], p[1]] for p in mug_outer_mm])

    # Check for optional handle layers
    handle_enabled = True
    try:
        handle_rail_paths = get_layer_paths(svg_root, "handle rails")
        side_rail_paths = get_layer_paths(svg_root, "handle side rails")
        profile_paths = get_layer_paths(svg_root, "handle profile")
    except ValueError:
        handle_enabled = False

    handle_stations_3d = []
    stations = []
    if handle_enabled:
        inner_rail_mm = svg_to_mm(handle_rail_paths[0])
        outer_rail_mm = svg_to_mm(handle_rail_paths[1])

        side_rail = [(to_mm(p[0] * scale, doc_units), to_mm(p[1] * scale, doc_units))
                     for p in side_rail_paths[0]]

        handle_profile = [(p[0], p[1]) for p in profile_paths[0]]

        def mug_true_radius_at_z(z):
            return mug_surface.radius_at_z(z)

        midpoints = _build_midpoint_curve(inner_rail_mm, outer_rail_mm)
        mid_cl = _cumulative_chord_lengths(midpoints)
        mid_total = mid_cl[-1]

        n_stations = compute_n(fn, fa, fs, mid_total)
        n_stations = max(n_stations, 5)

        import math
        from lib.units import to_mm as _to_mm

        avg_radius = (sum(p[0] for p in mug_outer_mm) / len(mug_outer_mm)
                      - mug_surface.axis_x)
        circumference = 2.0 * math.pi * avg_radius
        n_rev = compute_n(fn, fa, fs, circumference)
        body_seg_len = circumference / n_rev
        handle_seg_len = mid_total / n_stations

        mm_per_svg = _to_mm(scale, doc_units)
        svg_body_seg = body_seg_len / mm_per_svg
        svg_handle_seg = handle_seg_len / mm_per_svg

        mug_body_paths = get_layer_paths(svg_root, "mug body",
                                         max_seg_len=svg_body_seg)
        profile_paths = get_layer_paths(svg_root, "handle profile",
                                        max_seg_len=svg_handle_seg)
        body_mm = svg_to_mm(mug_body_paths[0])
        mug_outer_mm, mug_inner_mm = split_body_profile(body_mm)
        rim_z = mug_outer_mm[0][1]
        inner_r = mug_inner_mm[0][0]
        tube_top = rim_z + filler_tube_height
        mug_inner_mm = [(inner_r, tube_top)] + list(mug_inner_mm)
        handle_profile = [(p[0], p[1]) for p in profile_paths[0]]

        stations = sample_rails(inner_rail_mm, outer_rail_mm, n_stations)
        stations = apply_side_rails(stations, side_rail, side_rail)

        handle_stations_3d = generate_handle_stations(
            handle_profile, stations,
            mug_axis_x=mug_surface.axis_x,
            mug_radius_at_z=mug_true_radius_at_z,
        )

    else:
        import math
        from lib.units import to_mm as _to_mm

        avg_radius = (sum(p[0] for p in mug_outer_mm) / len(mug_outer_mm)
                      - mug_surface.axis_x)
        circumference = 2.0 * math.pi * avg_radius
        n_rev = compute_n(fn, fa, fs, circumference)
        body_seg_len = circumference / n_rev

        mm_per_svg = _to_mm(scale, doc_units)
        svg_body_seg = body_seg_len / mm_per_svg

        mug_body_paths = get_layer_paths(svg_root, "mug body",
                                         max_seg_len=svg_body_seg)
        body_mm = svg_to_mm(mug_body_paths[0])
        mug_outer_mm, mug_inner_mm = split_body_profile(body_mm)
        rim_z = mug_outer_mm[0][1]
        inner_r = mug_inner_mm[0][0]
        tube_top = rim_z + filler_tube_height
        mug_inner_mm = [(inner_r, tube_top)] + list(mug_inner_mm)

    # Raw polygon vertices in path order — X = radius from document origin.
    # Data is at actual (fired) size; clay shrinkage scaling is in the SCAD files.
    scad_outer_profile = [[p[0], p[1]] for p in mug_outer_mm]
    scad_inner_profile = [[p[0], p[1]] for p in mug_inner_mm]

    # Extract maker's mark (optional layer)
    mark_raw = get_layer_mark_polygons(svg_root, "mark")
    mark_enabled = len(mark_raw) > 0
    mark_polygons = []
    if mark_enabled:
        mark_mm = []
        for poly in mark_raw:
            converted = [
                (-to_mm(p[0] * scale, doc_units),
                 -to_mm(p[1] * scale, doc_units))
                for p in poly
            ]
            mark_mm.append(converted)
        all_x = [p[0] for poly in mark_mm for p in poly]
        all_y = [p[1] for poly in mark_mm for p in poly]
        cx = (min(all_x) + max(all_x)) / 2
        cy = (min(all_y) + max(all_y)) / 2
        mark_polygons = [
            [(p[0] - cx, p[1] - cy) for p in poly]
            for poly in mark_mm
        ]

    # Detect foot concavity for mould type
    concavity = mug_surface.detect_foot_concavity()
    mould_params = {
        "plaster_thickness": 30.0,
        "wall_thickness": 0.8,
        "natch_radius": 6.75,
        "funnel_wall_angle": 30.0,
        "funnel_wall": 1.5,
        "flange_width": 3.0,
        "breather_hole_dia": 1.0,
        "breather_hole_count": 6,
        "mark_depth": mark_depth,
        "mark_inset": mark_inset,
        "mark_draft_angle": mark_draft_angle,
        "mark_layer_height": mark_layer_height,
        "mark_enabled": mark_enabled,
    }
    if concavity or mark_enabled:
        mould_params["mould_type"] = 3
        if concavity:
            mould_params["foot_concavity_z"] = concavity[0]
            mould_params["foot_concavity_radius"] = concavity[1]
    else:
        mould_params["mould_type"] = 2

    if handle_enabled:
        handle_stations_out = [
            [[pt[0], pt[1], pt[2]] for pt in poly]
            for poly in handle_stations_3d
        ]
        norm_profile = normalize_profile(handle_profile)
        handle_stations_out = nudge_handle_stations(
            handle_stations_out, scad_outer_profile,
            axis_x=mug_surface.axis_x,
            station_frames=stations,
            norm_profile=norm_profile,
        )
        handle_path_out = [
            [s.centroid[0], s.centroid[1], s.centroid[2]]
            for s in stations
        ]
    else:
        handle_stations_out = []
        handle_path_out = []

    data = {
        "mug_outer_profile": scad_outer_profile,
        "mug_inner_profile": scad_inner_profile,
        "mark_polygons": mark_polygons if mark_enabled else None,
        "handle_stations": handle_stations_out,
        "handle_path": handle_path_out,
        "mug_params": {
            "fn": fn,
            "fa": fa,
            "fs": fs,
            "axis_x": mug_surface.axis_x,
            "clay_shrinkage_pct": clay_shrinkage,
            "handle_enabled": handle_enabled,
            **mould_params,
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
        assert (tmp_path / "funnel.scad").exists()

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
        assert "plaster_thickness" in text
        assert "wall_thickness" in text
        assert "natch_radius" in text
        assert "mould_type" in text
        assert "funnel_wall_angle" in text
        assert "funnel_wall" in text
        assert "flange_width" in text
        assert "breather_hole_dia" in text
        assert "breather_hole_count" in text

    def test_numeric_consistency(self, tmp_path):
        """Run pipeline twice and verify outputs match within tolerance."""
        data1 = _run_pipeline(FIXTURE_SVG, tmp_path / "run1", fn=20)
        data2 = _run_pipeline(FIXTURE_SVG, tmp_path / "run2", fn=20)

        for p1, p2 in zip(data1["mug_outer_profile"], data2["mug_outer_profile"]):
            assert p1 == pytest.approx(p2, abs=1e-6)

        for s1, s2 in zip(data1["handle_stations"], data2["handle_stations"]):
            for p1, p2 in zip(s1, s2):
                assert p1 == pytest.approx(p2, abs=1e-6)

    def test_mould_scad_copied(self, tmp_path):
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)
        assert (tmp_path / "mould.scad").exists()

    def test_auto_resolution(self, tmp_path):
        """Test with auto resolution (fn=0) — should still produce valid output."""
        data = _run_pipeline(FIXTURE_SVG, tmp_path, fn=0, fa=12, fs=2)
        assert len(data["handle_stations"]) >= 5

    def test_clay_shrinkage(self, tmp_path):
        """Emitted data is at actual size; clay_shrinkage_pct is a param for SCAD."""
        data_no = _run_pipeline(FIXTURE_SVG, tmp_path / "no_shrink", fn=20,
                                clay_shrinkage=0.0)
        data_10 = _run_pipeline(FIXTURE_SVG, tmp_path / "shrink_10", fn=20,
                                clay_shrinkage=10.0)

        # Profile data should be identical (actual size, not pre-scaled)
        for p0, p10 in zip(data_no["mug_outer_profile"],
                           data_10["mug_outer_profile"]):
            assert p10[0] == pytest.approx(p0[0], abs=1e-6)
            assert p10[1] == pytest.approx(p0[1], abs=1e-6)

        text = (tmp_path / "shrink_10" / "mug_params.scad").read_text()
        assert "clay_shrinkage_pct = 10.0" in text

    def test_mark_params_written(self, tmp_path):
        """Mark params are always emitted, even without a mark layer."""
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)
        text = (tmp_path / "mug_params.scad").read_text()
        assert "mark_enabled = " in text
        assert "mark_depth = " in text
        assert "mark_inset = " in text
        assert "mark_draft_angle = " in text

    def test_mark_polygon_file_exists(self, tmp_path):
        """mark_polygon.scad is always emitted."""
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)
        assert (tmp_path / "mark_polygon.scad").exists()

    def test_no_mark_layer_backward_compat(self, tmp_path):
        """Without a mark layer, mark_enabled is false and polygons empty."""
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)
        text = (tmp_path / "mug_params.scad").read_text()
        assert "mark_enabled = false" in text
        mark_text = (tmp_path / "mark_polygon.scad").read_text()
        assert "mark_points = []" in mark_text
        assert "mark_paths = []" in mark_text

    def test_mark_layer_extraction(self, tmp_path):
        """With a mark layer, mark_enabled is true and polygons are populated."""
        fixture = FIXTURE_SVG.parent / "sample_with_mark.svg"
        _run_pipeline(fixture, tmp_path, fn=20)
        text = (tmp_path / "mug_params.scad").read_text()
        assert "mark_enabled = true" in text
        mark_text = (tmp_path / "mark_polygon.scad").read_text()
        assert "mark_points" in mark_text
        assert "mark_points = []" not in mark_text
        assert "mark_paths" in mark_text
        assert "mark_paths = []" not in mark_text

    def test_no_handle_pipeline(self, tmp_path):
        """Pipeline works without handle layers."""
        fixture = FIXTURE_SVG.parent / "sample_no_handle.svg"
        data = _run_pipeline(fixture, tmp_path, fn=20)

        assert (tmp_path / "mug_outer_profile.scad").exists()
        assert (tmp_path / "mug_inner_profile.scad").exists()
        assert (tmp_path / "handle_stations.scad").exists()
        assert (tmp_path / "handle_path.scad").exists()
        assert (tmp_path / "mug_params.scad").exists()
        assert (tmp_path / "mug.scad").exists()

        assert data["handle_stations"] == []
        assert data["handle_path"] == []

        text = (tmp_path / "mug_params.scad").read_text()
        assert "handle_enabled = false" in text

        hs_text = (tmp_path / "handle_stations.scad").read_text()
        assert "handle_stations = []" in hs_text

        hp_text = (tmp_path / "handle_path.scad").read_text()
        assert "handle_path = []" in hp_text

    def test_no_handle_profiles_valid(self, tmp_path):
        """Mug profiles are valid even without handle layers."""
        fixture = FIXTURE_SVG.parent / "sample_no_handle.svg"
        _run_pipeline(fixture, tmp_path, fn=20)

        outer_text = (tmp_path / "mug_outer_profile.scad").read_text()
        outer = _parse_scad_array(outer_text, "mug_outer_profile")
        assert len(outer) >= 2

    def test_handle_enabled_with_handle(self, tmp_path):
        """handle_enabled is true when all handle layers are present."""
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)
        text = (tmp_path / "mug_params.scad").read_text()
        assert "handle_enabled = true" in text

    def test_handle_snap_to_mug_in_scad(self, tmp_path):
        """Static SCAD files contain snap_to_mug for handle attachment."""
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)
        mug_text = (tmp_path / "mug.scad").read_text()
        assert "snap_to_mug" in mug_text
        mould_text = (tmp_path / "mould.scad").read_text()
        assert "snap_to_mug" in mould_text
