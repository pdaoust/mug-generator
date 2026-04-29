"""Tests for scad_writer.py."""

import re

import pytest

from lib.scad_writer import run_all_emitters


def _parse_scad_array(text: str, var_name: str) -> list:
    pattern = rf'{var_name}\s*=\s*(\[[\s\S]*?\]);\s*$'
    match = re.search(pattern, text, re.MULTILINE)
    assert match, f"Could not find '{var_name}' in:\n{text[:200]}"
    return eval(match.group(1))  # noqa: S307


def _base_data(**overrides):
    """Minimal valid data dict for all emitters."""
    d = {
        "mug_body_profile_bez": [
            [35.0, 100.0], [35.0, 70.0], [35.0, 40.0],
            [35.0, 5.0], [33.0, 2.0], [30.0, 0.0],
            [0.0, 0.0],
        ],
        "mug_body_profile_closed": True,
        "handle_inner_rail_bez": None,
        "handle_outer_rail_bez": None,
        "handle_profile_bez": None,
        "handle_side_rail_polyline": None,
        "handle_n_stations": None,
        "mug_params": {"fn": 0, "fa": 12, "fs": 2},
    }
    d.update(overrides)
    return d


class TestScadWriter:
    def test_mug_body_profile(self, tmp_path):
        run_all_emitters(_base_data(), tmp_path)

        text = (tmp_path / "mug_body_profile.scad").read_text()
        assert "Auto-generated" in text
        arr = _parse_scad_array(text, "mug_body_profile_bez")
        assert len(arr) == 7
        assert arr[0] == pytest.approx([35.0, 100.0], abs=1e-4)
        assert "mug_body_profile_closed = true" in text

    def test_handle_bezpaths(self, tmp_path):
        run_all_emitters(_base_data(
            handle_inner_rail_bez=[[40, 50], [45, 60], [50, 70], [55, 80]],
            handle_outer_rail_bez=[[60, 50], [65, 60], [70, 70], [75, 80]],
            handle_profile_bez=[[0, 0], [1, 0], [1, 1], [0, 1]],
            handle_side_rail_polyline=[[3, 0], [3, 100]],
            handle_n_stations=10,
        ), tmp_path)

        text = (tmp_path / "handle_bezpaths.scad").read_text()
        assert "handle_n_stations = 10" in text
        inner = _parse_scad_array(text, "handle_inner_rail_bez")
        assert inner[0] == pytest.approx([40, 50], abs=1e-4)

    def test_mug_params_fn(self, tmp_path):
        run_all_emitters(_base_data(mug_params={"fn": 64, "axis_x": 5.0}), tmp_path)

        text = (tmp_path / "mug_params.scad").read_text()
        assert "$fn = 64" in text
        assert "mug_axis_x" in text

    def test_mug_params_fa_fs(self, tmp_path):
        run_all_emitters(_base_data(mug_params={"fn": 0, "fa": 6, "fs": 1}), tmp_path)

        text = (tmp_path / "mug_params.scad").read_text()
        assert "$fa = 6" in text
        assert "$fs = 1" in text

    def test_mould_params_2part(self, tmp_path):
        run_all_emitters(_base_data(mug_params={
            "fn": 0, "fa": 12, "fs": 2, "axis_x": 0.0,
            "plaster_thickness": 30.0, "wall_thickness": 0.8,
            "natch_radius": 6.75, "mould_type": 2,
        }), tmp_path)
        text = (tmp_path / "mug_params.scad").read_text()
        assert "plaster_thickness = 30" in text
        assert "wall_thickness = 0.8" in text
        assert "natch_radius = 6.75" in text
        assert "mould_type = 2" in text
        assert "foot_concavity_z" not in text

    def test_mould_params_3part(self, tmp_path):
        run_all_emitters(_base_data(mug_params={
            "fn": 20, "axis_x": 0.0,
            "plaster_thickness": 30.0, "wall_thickness": 0.8,
            "natch_radius": 6.75, "mould_type": 3,
            "foot_concavity_z": 6.0, "foot_concavity_radius": 30.0,
        }), tmp_path)
        text = (tmp_path / "mug_params.scad").read_text()
        assert "mould_type = 3" in text
        assert "foot_concavity_z = 6" in text
        assert "foot_concavity_radius = 30" in text

    def test_filler_tube_height(self, tmp_path):
        run_all_emitters(_base_data(mug_params={
            "fn": 0, "fa": 12, "fs": 2,
            "filler_tube_height": 15.0,
        }), tmp_path)
        text = (tmp_path / "mug_params.scad").read_text()
        assert "filler_tube_height = 15" in text

    def test_alignment_type_natches(self, tmp_path):
        run_all_emitters(_base_data(mug_params={
            "fn": 0, "fa": 12, "fs": 2,
            "alignment_type": "natches", "natch_radius": 6.75,
        }), tmp_path)
        text = (tmp_path / "mug_params.scad").read_text()
        assert 'alignment_type = "natches"' in text

    def test_alignment_type_keys(self, tmp_path):
        run_all_emitters(_base_data(mug_params={
            "fn": 0, "fa": 12, "fs": 2,
            "alignment_type": "keys", "natch_radius": 6.75,
        }), tmp_path)
        text = (tmp_path / "mug_params.scad").read_text()
        assert 'alignment_type = "keys"' in text

    def test_key_tolerance(self, tmp_path):
        run_all_emitters(_base_data(mug_params={
            "fn": 0, "fa": 12, "fs": 2,
            "alignment_type": "keys", "natch_radius": 6.75,
            "key_tolerance": 0.50,
        }), tmp_path)
        text = (tmp_path / "mug_params.scad").read_text()
        assert "key_tolerance = 0.5" in text

    def test_numeric_tolerance(self, tmp_path):
        bez = [[12.3456789, 98.7654321], [12, 80], [12, 60],
               [10, 40], [8, 20], [4, 5], [0.001, 0.002]]
        run_all_emitters(_base_data(mug_body_profile_bez=bez), tmp_path)

        text = (tmp_path / "mug_body_profile.scad").read_text()
        arr = _parse_scad_array(text, "mug_body_profile_bez")
        assert arr[0] == pytest.approx(bez[0], abs=1e-4)
        assert arr[-1] == pytest.approx(bez[-1], abs=1e-4)
