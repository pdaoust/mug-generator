"""Tests for scad_writer.py."""

import re

import pytest

from lib.scad_writer import run_all_emitters


def _parse_scad_array(text: str, var_name: str) -> list:
    """Simple parser: extract a variable assignment from .scad text and eval it."""
    pattern = rf'{var_name}\s*=\s*(\[[\s\S]*?\]);\s*$'
    match = re.search(pattern, text, re.MULTILINE)
    assert match, f"Could not find '{var_name}' in:\n{text[:200]}"
    raw = match.group(1)
    return eval(raw)  # noqa: S307 — test-only, trusted input


def _base_data(**overrides):
    """Minimal valid data dict for all emitters."""
    d = {
        "mug_outer_profile": [[0.0, 0.0], [30.0, 50.0], [35.0, 100.0]],
        "mug_inner_profile": [[0.0, 3.0], [27.0, 50.0], [32.0, 97.0]],
        "handle_stations": [[[1, 2, 3], [4, 5, 6]]],
        "mug_params": {"fn": 0, "fa": 12, "fs": 2},
    }
    d.update(overrides)
    return d


class TestScadWriter:
    def test_mug_outer_profile(self, tmp_path):
        run_all_emitters(_base_data(), tmp_path)

        text = (tmp_path / "mug_outer_profile.scad").read_text()
        assert "Auto-generated" in text
        arr = _parse_scad_array(text, "mug_outer_profile")
        assert len(arr) == 3
        assert arr[0] == pytest.approx([0.0, 0.0], abs=1e-4)
        assert arr[2] == pytest.approx([35.0, 100.0], abs=1e-4)

    def test_mug_inner_profile(self, tmp_path):
        run_all_emitters(_base_data(), tmp_path)

        text = (tmp_path / "mug_inner_profile.scad").read_text()
        arr = _parse_scad_array(text, "mug_inner_profile")
        assert len(arr) == 3
        assert arr[0] == pytest.approx([0.0, 3.0], abs=1e-4)

    def test_handle_stations(self, tmp_path):
        stations = [
            [[10.0, 0.0, 5.0], [20.0, 0.0, 5.0], [15.0, 3.0, 5.0]],
            [[10.0, 0.0, 15.0], [20.0, 0.0, 15.0], [15.0, 3.0, 15.0]],
        ]
        run_all_emitters(_base_data(handle_stations=stations), tmp_path)

        text = (tmp_path / "handle_stations.scad").read_text()
        arr = _parse_scad_array(text, "handle_stations")
        assert len(arr) == 2
        assert len(arr[0]) == 3
        assert arr[0][0] == pytest.approx([10.0, 0.0, 5.0], abs=1e-4)

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

    def test_handle_path_conditional(self, tmp_path):
        run_all_emitters(_base_data(), tmp_path)
        assert not (tmp_path / "handle_path.scad").exists()

        run_all_emitters(_base_data(handle_path=[[1, 0, 2], [3, 0, 4]]), tmp_path)
        assert (tmp_path / "handle_path.scad").exists()

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

    def test_numeric_tolerance(self, tmp_path):
        outer = [[12.3456789, 98.7654321], [0.001, 0.002]]
        run_all_emitters(_base_data(mug_outer_profile=outer), tmp_path)

        text = (tmp_path / "mug_outer_profile.scad").read_text()
        arr = _parse_scad_array(text, "mug_outer_profile")
        assert arr[0] == pytest.approx(outer[0], abs=1e-4)
        assert arr[1] == pytest.approx(outer[1], abs=1e-4)
