"""Integration test: full pipeline from SVG to .scad output.

The Python side of the pipeline is now a thin bezpath emitter; tessellation
and station generation live in OpenSCAD/BOSL2.  These tests exercise the
emitter chain via stdlib XML parsing (no inkex dependency).
"""

import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from lib.svg_layers import get_layer_paths_bez, get_layer_mark_bezpaths
from lib.units import to_mm, parse_doc_units, parse_viewbox_bottom, parse_viewbox_scale
from lib.bezier_eval import (
    bezpath_length, bezpath_max_axis, bezpath_min_axis,
    detect_foot_concavity_bez, split_outer_bez_at_rim,
)
from lib.openscad_params import compute_n
from lib.scad_writer import run_all_emitters


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
    """Mirror mug_generator.effect() without inkex; emit data files."""
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

    body_layer = get_layer_paths_bez(svg_root, "mug body")
    body_bez_raw, body_bez_closed = body_layer[0]
    body_bez_mm = svg_to_mm(body_bez_raw)

    handle_enabled = True
    try:
        rail_layer = get_layer_paths_bez(svg_root, "handle rails")
        side_rail_layer = get_layer_paths_bez(svg_root, "handle side rails")
        profile_layer = get_layer_paths_bez(svg_root, "handle profile")
    except ValueError:
        handle_enabled = False

    inner_rail_bez_mm = []
    outer_rail_bez_mm = []
    side_rail_polyline_mm = []
    handle_profile_bez_mm = []
    n_stations = 0

    if handle_enabled:
        inner_rail_bez_mm = svg_to_mm(rail_layer[0][0])
        outer_rail_bez_mm = svg_to_mm(rail_layer[1][0])
        handle_profile_bez_mm = [(p[0], p[1]) for p in profile_layer[0][0]]
        side_rail_polyline_mm = [
            (to_mm(p[0] * scale, doc_units),
             to_mm(p[1] * scale, doc_units))
            for p in side_rail_layer[0][0]
        ]
        mid_len = (bezpath_length(inner_rail_bez_mm)
                   + bezpath_length(outer_rail_bez_mm)) / 2
        n_stations = compute_n(fn, fa, fs, mid_len)

    mark_raw_bez = get_layer_mark_bezpaths(svg_root, "mark")
    mark_enabled = len(mark_raw_bez) > 0
    mark_bezpaths = []
    if mark_enabled:
        for bez, _closed in mark_raw_bez:
            mark_bezpaths.append([
                (-to_mm(p[0] * scale, doc_units),
                 -to_mm(p[1] * scale, doc_units))
                for p in bez
            ])

    outer_bez = split_outer_bez_at_rim(body_bez_mm)
    concavity = detect_foot_concavity_bez(outer_bez)
    lip_pt = bezpath_max_axis(outer_bez, 1)
    foot_pt = bezpath_min_axis(outer_bez, 1)
    z_lip = lip_pt[1]
    lip_r = lip_pt[0]
    z_min = foot_pt[1]

    cs = 100.0 / (100.0 - clay_shrinkage) if clay_shrinkage > 0 else 1.0

    mould_params = {
        "alignment_type": "natches",
        "plaster_thickness": 30.0,
        "wall_thickness": 0.8,
        "natch_radius": 6.75,
        "key_tolerance": 0.5,
        "funnel_wall_angle": 30.0,
        "funnel_wall": 1.5,
        "flange_width": 3.0,
        "breather_hole_dia": 1.0,
        "breather_hole_count": 6,
        "mark_depth": mark_depth,
        "mark_inset": mark_inset,
        "mark_draft_angle": mark_draft_angle,
        "mark_layer_height": mark_layer_height,
        "mark_fa": 12.0,
        "mark_fs": 0.25,
        "mark_enabled": mark_enabled,
    }
    if concavity or mark_enabled:
        mould_params["mould_type"] = 3
        if concavity:
            mould_params["foot_concavity_z"] = concavity[0]
            mould_params["foot_concavity_radius"] = concavity[1]
    else:
        mould_params["mould_type"] = 2
    needs_base = bool(concavity) or bool(mark_enabled and mark_inset)
    mould_params["needs_base"] = needs_base
    mould_params["z_min_scaled"] = z_min * cs
    mould_params["z_lip_scaled"] = z_lip * cs
    mould_params["lip_r_scaled"] = lip_r * cs

    exports_resolved = dict(DEFAULT_EXPORTS)
    if exports is not None:
        exports_resolved.update(exports)
    if not exports_resolved["slump_mould"]:
        exports_resolved["slump_rib"] = False
    if not exports_resolved["hump_mould"]:
        exports_resolved["hump_rib"] = False

    data = {
        "exports": exports_resolved,
        "mug_body_profile_bez": [list(p) for p in body_bez_mm],
        "mug_body_profile_closed": body_bez_closed,
        "handle_inner_rail_bez": (
            [list(p) for p in inner_rail_bez_mm] if handle_enabled else None
        ),
        "handle_outer_rail_bez": (
            [list(p) for p in outer_rail_bez_mm] if handle_enabled else None
        ),
        "handle_side_rail_polyline": (
            [list(p) for p in side_rail_polyline_mm] if handle_enabled else None
        ),
        "handle_profile_bez": (
            [list(p) for p in handle_profile_bez_mm] if handle_enabled else None
        ),
        "handle_n_stations": n_stations if handle_enabled else None,
        "mark_bezpaths": mark_bezpaths if mark_enabled else None,
        "mug_params": {
            "fn": fn,
            "fa": fa,
            "fs": fs,
            "axis_x": 0.0,
            "filler_tube_height": 15.0,
            "filler_tube_angle": 20.0,
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
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)

        assert (tmp_path / "mug_body_profile.scad").exists()
        assert (tmp_path / "handle_bezpaths.scad").exists()
        assert (tmp_path / "mug_params.scad").exists()
        assert (tmp_path / "prototype.scad").exists()
        assert (tmp_path / "funnel.scad").exists()

    def test_body_bezpath_valid(self, tmp_path):
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)

        body_text = (tmp_path / "mug_body_profile.scad").read_text()
        bez = _parse_scad_array(body_text, "mug_body_profile_bez")
        # Cubic bezpath: 3n+1 knots.
        assert len(bez) >= 4
        assert (len(bez) - 1) % 3 == 0
        assert "mug_body_profile_closed = true" in body_text

    def test_handle_bezpaths_valid(self, tmp_path):
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)
        text = (tmp_path / "handle_bezpaths.scad").read_text()
        for name in (
            "handle_inner_rail_bez",
            "handle_outer_rail_bez",
            "handle_profile_bez",
            "handle_side_rail_polyline",
        ):
            assert name in text
        assert "handle_n_stations" in text

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

    def test_case_mould_scad_copied(self, tmp_path):
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)
        assert (tmp_path / "case_mould_original.scad").exists()
        assert (tmp_path / "case_mould_efficient.scad").exists()

    def test_new_scad_files_copied(self, tmp_path):
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)
        for name in ("hump_mould.scad", "slump_mould.scad",
                      "hump_mould_rib.scad",
                      "slump_mould_rib.scad"):
            assert (tmp_path / name).exists()

    def test_efficient_mould_derived_params(self, tmp_path):
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20, clay_shrinkage=10.0)
        text = (tmp_path / "mug_params.scad").read_text()
        for key in ("needs_base", "z_min_scaled", "z_lip_scaled",
                    "lip_r_scaled"):
            assert key in text

        # Fixture has a plain cylindrical foot (no concavity, no mark).
        assert "needs_base = false" in text

        m = re.search(r"z_min_scaled\s*=\s*([\d.]+);", text)
        assert m
        assert abs(float(m.group(1)) - 20.0 * 100.0 / 90.0) < 1e-3

    def test_rib_params_in_mug_params(self, tmp_path):
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)
        text = (tmp_path / "mug_params.scad").read_text()
        assert "rib_thickness" in text
        assert "rib_taper" in text
        assert "rib_margin" in text
        assert "wheel_direction" in text
        assert "hump_rib_direction" in text

    def test_clay_shrinkage(self, tmp_path):
        _run_pipeline(FIXTURE_SVG, tmp_path / "no_shrink", fn=20,
                      clay_shrinkage=0.0)
        _run_pipeline(FIXTURE_SVG, tmp_path / "shrink_10", fn=20,
                      clay_shrinkage=10.0)
        text = (tmp_path / "shrink_10" / "mug_params.scad").read_text()
        assert "clay_shrinkage_pct = 10.0" in text

    def test_mark_params_written(self, tmp_path):
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)
        text = (tmp_path / "mug_params.scad").read_text()
        assert "mark_enabled = " in text
        assert "mark_depth = " in text
        assert "mark_inset = " in text
        assert "mark_draft_angle = " in text

    def test_mark_polygon_file_exists(self, tmp_path):
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)
        assert (tmp_path / "mark_polygon.scad").exists()

    def test_no_mark_layer(self, tmp_path):
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)
        text = (tmp_path / "mug_params.scad").read_text()
        assert "mark_enabled = false" in text
        mark_text = (tmp_path / "mark_polygon.scad").read_text()
        assert "mark_bezpaths = []" in mark_text

    def test_mark_layer_extraction(self, tmp_path):
        fixture = FIXTURE_SVG.parent / "sample_with_mark.svg"
        _run_pipeline(fixture, tmp_path, fn=20)
        text = (tmp_path / "mug_params.scad").read_text()
        assert "mark_enabled = true" in text
        mark_text = (tmp_path / "mark_polygon.scad").read_text()
        assert "mark_bezpaths" in mark_text
        assert "mark_bezpaths = []" not in mark_text

    def test_no_handle_pipeline(self, tmp_path):
        fixture = FIXTURE_SVG.parent / "sample_no_handle.svg"
        data = _run_pipeline(fixture, tmp_path, fn=20)

        assert (tmp_path / "mug_body_profile.scad").exists()
        assert (tmp_path / "handle_bezpaths.scad").exists()
        assert (tmp_path / "mug_params.scad").exists()
        assert (tmp_path / "prototype.scad").exists()

        assert data["handle_inner_rail_bez"] is None

        text = (tmp_path / "mug_params.scad").read_text()
        assert "handle_enabled = false" in text

        hb_text = (tmp_path / "handle_bezpaths.scad").read_text()
        assert "handle_inner_rail_bez = []" in hb_text

    def test_handle_enabled_with_handle(self, tmp_path):
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)
        text = (tmp_path / "mug_params.scad").read_text()
        assert "handle_enabled = true" in text

    def test_handle_snap_to_mug_in_scad(self, tmp_path):
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20)
        mug_text = (tmp_path / "prototype.scad").read_text()
        assert "snap_to_mug" in mug_text
        mould_text = (tmp_path / "case_mould_original.scad").read_text()
        assert "snap_to_mug" in mould_text


class TestSelectiveExport:
    def test_only_funnel(self, tmp_path):
        ex = {k: False for k in DEFAULT_EXPORTS}
        ex["funnel"] = True
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20, exports=ex)

        assert (tmp_path / "funnel.scad").exists()
        assert (tmp_path / "mug_params.scad").exists()
        assert (tmp_path / "mug_body_profile.scad").exists()

        for name in ("prototype.scad", "case_mould_original.scad",
                     "case_mould_efficient.scad", "slump_mould.scad",
                     "hump_mould.scad", "slump_mould_rib.scad",
                     "hump_mould_rib.scad"):
            assert not (tmp_path / name).exists()

        assert not (tmp_path / "handle_bezpaths.scad").exists()
        assert not (tmp_path / "mark_polygon.scad").exists()

    def test_rib_demoted_when_mould_unchecked(self, tmp_path):
        ex = {k: False for k in DEFAULT_EXPORTS}
        ex["slump_rib"] = True
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20, exports=ex)

        assert not (tmp_path / "slump_mould.scad").exists()
        assert not (tmp_path / "slump_mould_rib.scad").exists()

    def test_ribs_are_independent(self, tmp_path):
        ex = dict(DEFAULT_EXPORTS)
        ex["slump_rib"] = False
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20, exports=ex)

        assert (tmp_path / "hump_mould_rib.scad").exists()
        assert not (tmp_path / "slump_mould_rib.scad").exists()

    def test_mug_params_slimmed(self, tmp_path):
        ex = {k: False for k in DEFAULT_EXPORTS}
        ex["funnel"] = True
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20, exports=ex)

        text = (tmp_path / "mug_params.scad").read_text()
        assert "funnel_wall_angle" in text
        assert "plaster_thickness" not in text
        assert "natch_radius" not in text
        assert "rib_thickness" not in text
        assert "hump_rib_direction" not in text
        assert "mark_depth" not in text

    def test_case_mould_volumes_are_sane(self, tmp_path):
        openscad = shutil.which("openscad-nightly") or shutil.which("openscad")
        if not openscad:
            pytest.skip("openscad not installed")

        home_tmp = Path.home() / "tmp" / f"pytest_case_mould_{os.getpid()}"
        home_tmp.mkdir(parents=True, exist_ok=True)
        try:
            _run_pipeline(FIXTURE_SVG, home_tmp, fn=36, clay_shrinkage=10.0)
            result = subprocess.run(
                [openscad, "-o", str(home_tmp / "out.stl"),
                 "--export-format", "binstl",
                 str(home_tmp / "case_mould_original.scad")],
                capture_output=True, text=True, timeout=180,
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

        assert 100 < slip_fill < 1500
        assert 1000 < half_a < 4000

    def test_prototype_only_keeps_mark_polygon(self, tmp_path):
        ex = {k: False for k in DEFAULT_EXPORTS}
        ex["prototype"] = True
        _run_pipeline(FIXTURE_SVG, tmp_path, fn=20, exports=ex)

        assert (tmp_path / "prototype.scad").exists()
        assert (tmp_path / "handle_bezpaths.scad").exists()
        assert (tmp_path / "mark_polygon.scad").exists()
        assert not (tmp_path / "funnel.scad").exists()
        assert not (tmp_path / "case_mould_original.scad").exists()
