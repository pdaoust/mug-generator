"""Integration test: full pipeline from SVG to .scad output."""

import os
import re
import shutil
import subprocess
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


DEFAULT_EXPORTS = {
    "prototype": True,
    "case_mould": True,
    "case_mould_efficient": True,
    "funnel": True,
    "slump_mould": True,
    "slump_rib": True,
    "hump_mould": True,
    "hump_rib": True,
}


def _run_pipeline(svg_path: Path, output_dir: Path, fn=0, fa=12, fs=2,
                   clay_shrinkage=0.0, mark_depth=1.0, mark_inset=True,
                   mark_draft_angle=45.0, mark_layer_height=0.2,
                   exports=None):
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
    body_profile, foot_idx = split_body_profile(body_mm)
    filler_tube_height = 15.0
    mug_outer_mm = body_profile[:foot_idx + 1]

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

        from lib.units import to_mm as _to_mm

        mm_per_svg = _to_mm(scale, doc_units)
        if fn > 0:
            svg_fa = 360.0 / fn
            svg_fs = None
        else:
            svg_fa = fa
            svg_fs = fs / mm_per_svg if mm_per_svg > 0 else None

        mug_body_paths = get_layer_paths(svg_root, "mug body",
                                         fa_deg=svg_fa, fs=svg_fs)
        profile_paths = get_layer_paths(svg_root, "handle profile",
                                        fa_deg=svg_fa, fs=svg_fs)
        body_mm = svg_to_mm(mug_body_paths[0])
        body_profile, foot_idx = split_body_profile(body_mm)
        mug_outer_mm = body_profile[:foot_idx + 1]
        handle_profile = [(p[0], p[1]) for p in profile_paths[0]]

        stations = sample_rails(inner_rail_mm, outer_rail_mm, n_stations)
        stations = apply_side_rails(stations, side_rail, side_rail)

        handle_stations_3d = generate_handle_stations(
            handle_profile, stations,
            mug_axis_x=mug_surface.axis_x,
            mug_radius_at_z=mug_true_radius_at_z,
        )

    else:
        from lib.units import to_mm as _to_mm

        mm_per_svg = _to_mm(scale, doc_units)
        if fn > 0:
            svg_fa = 360.0 / fn
            svg_fs = None
        else:
            svg_fa = fa
            svg_fs = fs / mm_per_svg if mm_per_svg > 0 else None

        mug_body_paths = get_layer_paths(svg_root, "mug body",
                                         fa_deg=svg_fa, fs=svg_fs)
        body_mm = svg_to_mm(mug_body_paths[0])
        body_profile, foot_idx = split_body_profile(body_mm)
        mug_outer_mm = body_profile[:foot_idx + 1]

    # Raw polygon vertices in path order — X = radius from document origin.
    # Data is at actual (fired) size; clay shrinkage scaling is in the SCAD files.
    scad_body_profile = [[p[0], p[1]] for p in body_profile]
    scad_outer_profile = scad_body_profile[:foot_idx + 1]

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
        "alignment_type": "natches",
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

    exports_resolved = dict(DEFAULT_EXPORTS)
    if exports is not None:
        exports_resolved.update(exports)
    # Subsidiary rib demotion, mirroring mug_generator.py
    if not exports_resolved["slump_mould"]:
        exports_resolved["slump_rib"] = False
    if not exports_resolved["hump_mould"]:
        exports_resolved["hump_rib"] = False

    data = {
        "exports": exports_resolved,
        "mug_body_profile": scad_body_profile,
        "mark_polygons": mark_polygons if mark_enabled else None,
        "handle_stations": handle_stations_out,
        "handle_path": handle_path_out,
        "mug_params": {
            "fn": fn,
            "fa": fa,
            "fs": fs,
            "axis_x": mug_surface.axis_x,
            "body_foot_idx": foot_idx,
            "filler_tube_height": filler_tube_height,
            "clay_shrinkage_pct": clay_shrinkage,
            "handle_enabled": handle_enabled,
            "rib_thickness": 2.0,
            "rib_taper": 10.0,
            "rib_margin": 10.0,
            "wheel_direction": "counterclockwise",
            "hump_rib_direction": "top",
            **mould_params,
        },
    }

    run_all_emitters(data, output_dir)
    return data


class TestIntegration:
    def test_full_pipeline(self, tmp_path):
        """Run full pipeline and verify output files exist and parse correctly."""
        data = _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)

        assert (tmp_path / "mug_body_profile.scad").exists()
        assert (tmp_path / "handle_stations.scad").exists()
        assert (tmp_path / "handle_path.scad").exists()
        assert (tmp_path / "mug_params.scad").exists()
        assert (tmp_path / "mug.scad").exists()
        assert (tmp_path / "funnel.scad").exists()

    def test_mug_profiles_valid(self, tmp_path):
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)

        body_text = (tmp_path / "mug_body_profile.scad").read_text()
        body = _parse_scad_array(body_text, "mug_body_profile")
        assert len(body) >= 4
        for pt in body:
            assert pt[0] >= -0.01, f"Negative radius in body profile: {pt}"

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

        for p1, p2 in zip(data1["mug_body_profile"], data2["mug_body_profile"]):
            assert p1 == pytest.approx(p2, abs=1e-6)

        for s1, s2 in zip(data1["handle_stations"], data2["handle_stations"]):
            for p1, p2 in zip(s1, s2):
                assert p1 == pytest.approx(p2, abs=1e-6)

    def test_case_mould_scad_copied(self, tmp_path):
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)
        assert (tmp_path / "case_mould_original.scad").exists()
        assert (tmp_path / "case_mould_efficient.scad").exists()

    def test_new_scad_files_copied(self, tmp_path):
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)
        for name in ("hump_mould.scad", "slump_mould.scad",
                      "hump_mould_jiggering_rib.scad",
                      "slump_mould_jiggering_rib.scad"):
            assert (tmp_path / name).exists(), f"{name} not copied"

    def test_jiggering_params_in_mug_params(self, tmp_path):
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)
        text = (tmp_path / "mug_params.scad").read_text()
        assert "rib_thickness" in text
        assert "rib_taper" in text
        assert "rib_margin" in text
        assert "wheel_direction" in text
        assert "hump_rib_direction" in text

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
        for p0, p10 in zip(data_no["mug_body_profile"],
                           data_10["mug_body_profile"]):
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

        assert (tmp_path / "mug_body_profile.scad").exists()
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
        """Mug body profile is valid even without handle layers."""
        fixture = FIXTURE_SVG.parent / "sample_no_handle.svg"
        _run_pipeline(fixture, tmp_path, fn=20)

        body_text = (tmp_path / "mug_body_profile.scad").read_text()
        body = _parse_scad_array(body_text, "mug_body_profile")
        assert len(body) >= 4

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
        mould_text = (tmp_path / "case_mould_original.scad").read_text()
        assert "snap_to_mug" in mould_text


class TestSelectiveExport:
    def test_only_funnel(self, tmp_path):
        """Exporting only the funnel skips moulds, ribs, prototype."""
        ex = {k: False for k in DEFAULT_EXPORTS}
        ex["funnel"] = True
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20, exports=ex)

        assert (tmp_path / "funnel.scad").exists()
        assert (tmp_path / "mug_params.scad").exists()
        assert (tmp_path / "mug_body_profile.scad").exists()

        for name in ("mug.scad", "case_mould_original.scad",
                     "case_mould_efficient.scad", "slump_mould.scad",
                     "hump_mould.scad", "slump_mould_jiggering_rib.scad",
                     "hump_mould_jiggering_rib.scad"):
            assert not (tmp_path / name).exists(), f"{name} should not be copied"

        # Shared consumers get skipped when no consumer is exported
        assert not (tmp_path / "handle_stations.scad").exists()
        assert not (tmp_path / "handle_path.scad").exists()
        assert not (tmp_path / "mark_polygon.scad").exists()

    def test_rib_demoted_when_mould_unchecked(self, tmp_path):
        """slump_rib is ignored when slump_mould is unchecked."""
        ex = {k: False for k in DEFAULT_EXPORTS}
        ex["slump_rib"] = True  # parent is False → should be demoted
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20, exports=ex)

        assert not (tmp_path / "slump_mould.scad").exists()
        assert not (tmp_path / "slump_mould_jiggering_rib.scad").exists()

    def test_ribs_are_independent(self, tmp_path):
        """Unchecking one rib doesn't affect the other."""
        ex = dict(DEFAULT_EXPORTS)
        ex["slump_rib"] = False
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20, exports=ex)

        assert (tmp_path / "hump_mould_jiggering_rib.scad").exists()
        assert not (tmp_path / "slump_mould_jiggering_rib.scad").exists()

    def test_mug_params_slimmed(self, tmp_path):
        """mug_params.scad omits params for unselected exports."""
        ex = {k: False for k in DEFAULT_EXPORTS}
        ex["funnel"] = True
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20, exports=ex)

        text = (tmp_path / "mug_params.scad").read_text()
        # Funnel keys present
        assert "funnel_wall_angle" in text
        # Mould / rib / mark keys absent
        assert "plaster_thickness" not in text
        assert "natch_radius" not in text
        assert "rib_thickness" not in text
        assert "hump_rib_direction" not in text
        assert "mark_depth" not in text

    def test_case_mould_volumes_are_sane(self, tmp_path):
        """Render case_mould_original.scad with openscad-nightly and check that the
        echoed volumes fall in plausible ranges for the fixture mug."""
        openscad = shutil.which("openscad-nightly") or shutil.which("openscad")
        if not openscad:
            pytest.skip("openscad not installed")

        # OpenSCAD snaps are confined to $HOME, so stage files there.
        home_tmp = Path.home() / "tmp" / f"pytest_case_mould_{os.getpid()}"
        home_tmp.mkdir(parents=True, exist_ok=True)
        try:
            _run_pipeline(FIXTURE_SVG, home_tmp, fn=36, clay_shrinkage=10.0)
            result = subprocess.run(
                [openscad, "-o", str(home_tmp / "out.stl"),
                 "--export-format", "binstl",
                 str(home_tmp / "case_mould_original.scad")],
                capture_output=True, text=True, timeout=120,
            )
        finally:
            shutil.rmtree(home_tmp, ignore_errors=True)

        stderr = result.stderr
        def _extract(label):
            m = re.search(rf'{label}:\s*(-?\d+)\s*mL', stderr)
            assert m, f"'{label}' not echoed; stderr:\n{stderr}"
            return int(m.group(1))

        slip_fill = _extract("Slip fill")
        half_a = _extract("Half A")
        base = _extract("Base")

        assert 100 < slip_fill < 1500, f"slip fill implausible: {slip_fill} mL"
        assert 1000 < half_a < 4000, f"half A implausible: {half_a} mL"
        assert 100 < base < 2000, f"base is implausible: {base} mL"

        # Regression check on the Y extrusion heights. The plaster-volume
        # bug that motivated these bounds came from treating the inner hull
        # as a solid of revolution instead of a Y-extruded prism; pin the
        # three heights so a future refactor can't silently collapse them
        # back to a single `_full_y`.
        m = re.search(
            r"Y_EXTENT inner_y_total=([\d.]+) outer_y_base=([\d.]+) "
            r"outer_y_keys=([\d.]+) mug_max_radius=([\d.]+) "
            r"plaster_thickness=([\d.]+) wall_thickness=([\d.]+) "
            r"key_r_socket=([\d.]+)",
            stderr,
        )
        assert m, f"Y_EXTENT line missing; stderr:\n{stderr}"
        inner_y, outer_y_base, outer_y_keys, mmr, pt, wt, krs = (
            float(v) for v in m.groups()
        )
        inner_half = mmr + pt
        assert abs(inner_y - 2 * inner_half) < 1e-2
        assert abs(outer_y_base - 2 * (inner_half + wt)) < 1e-2
        assert abs(outer_y_keys - 2 * (inner_half + krs + wt)) < 1e-2
        # outer must strictly contain inner on each side.
        assert outer_y_base > inner_y, (
            f"outer_y_base ({outer_y_base}) must exceed inner_y_total "
            f"({inner_y})."
        )

    def test_prototype_only_keeps_mark_polygon(self, tmp_path):
        """Prototype consumes mark_polygon; it must still be emitted."""
        ex = {k: False for k in DEFAULT_EXPORTS}
        ex["prototype"] = True
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20, exports=ex)

        assert (tmp_path / "mug.scad").exists()
        assert (tmp_path / "handle_stations.scad").exists()
        assert (tmp_path / "handle_path.scad").exists()
        assert (tmp_path / "mark_polygon.scad").exists()
        assert not (tmp_path / "funnel.scad").exists()
        assert not (tmp_path / "case_mould_original.scad").exists()
        assert not (tmp_path / "case_mould_efficient.scad").exists()
