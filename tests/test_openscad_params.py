"""Tests for openscad_params.py."""

import math

import pytest

from lib.openscad_params import compute_n


class TestComputeN:
    def test_fn_overrides(self):
        assert compute_n(fn=20, fa=12, fs=2, curve_length=100) == 20

    def test_fn_zero_uses_auto(self):
        # fa=12 → ceil(360/12)=30, fs=2 with length=100 → ceil(100/2)=50
        assert compute_n(fn=0, fa=12, fs=2, curve_length=100) == 50

    def test_minimum_five(self):
        # Very coarse settings, but minimum is 5
        assert compute_n(fn=0, fa=360, fs=1000, curve_length=10) == 5

    def test_fa_dominates(self):
        # fa=1 → ceil(360/1)=360, fs=1000 → ceil(10/1000)=1
        assert compute_n(fn=0, fa=1, fs=1000, curve_length=10) == 360

    def test_fs_dominates(self):
        # fa=180 → ceil(360/180)=2, fs=0.1 → ceil(100/0.1)=1000
        assert compute_n(fn=0, fa=180, fs=0.1, curve_length=100) == 1000

    def test_fn_one(self):
        assert compute_n(fn=1, fa=12, fs=2, curve_length=100) == 1
