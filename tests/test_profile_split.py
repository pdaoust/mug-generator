"""Tests for split_body_profile."""
import pytest
from lib.profile_split import split_body_profile


def _rect_profile(w, h, ccw=False):
    """Rectangular cross-section: width w (radius), height h.

    Outer goes from (w, h) down to (w, 0) to (0, 0).
    Inner goes from (0, h) straight down to (0, 0).
    Closed path CW: rim-right → bottom-right → bottom-left → top-left → rim.
    """
    pts = [
        (w, h),    # top-right (rim, outer side)
        (w, 0.0),  # bottom-right
        (0.0, 0.0),  # bottom-left (axis)
        (0.0, h),  # top-left (axis, inner side)
    ]
    if ccw:
        pts = list(reversed(pts))
    return pts


class TestReturnFormat:
    def test_returns_body_and_foot_idx(self):
        body, foot_idx = split_body_profile(_rect_profile(30, 100))
        assert isinstance(body, list)
        assert isinstance(foot_idx, int)

    def test_body_starts_at_split_point(self):
        body, _ = split_body_profile(_rect_profile(30, 100))
        assert body[0] == (30, 100)

    def test_foot_idx_points_to_axis(self):
        body, foot_idx = split_body_profile(_rect_profile(30, 100))
        assert body[foot_idx][0] < 0.1  # r ≈ 0

    def test_outer_is_first(self):
        """Points 0..foot_idx should be the outer side (larger radii)."""
        body, foot_idx = split_body_profile(_rect_profile(30, 100))
        outer = body[:foot_idx + 1]
        inner = body[foot_idx:]
        outer_max_r = max(p[0] for p in outer)
        inner_max_r = max(p[0] for p in inner)
        assert outer_max_r >= inner_max_r


class TestSplitPoint:
    def test_rectangular(self):
        body, _ = split_body_profile(_rect_profile(30, 100))
        assert body[0] == (30, 100)

    def test_flat_lip_picks_outermost(self):
        path = [
            (40, 100),   # outermost rim point
            (35, 100),   # inner rim point (same z)
            (35, 0.0),
            (0.0, 0.0),
            (0.0, 100),
        ]
        body, _ = split_body_profile(path)
        assert body[0] == (40, 100)


class TestOuterInnerClassification:
    def test_rectangular_outer_has_larger_area(self):
        body, foot_idx = split_body_profile(_rect_profile(30, 100))
        outer = body[:foot_idx + 1]
        assert max(p[0] for p in outer) == 30

    def test_ccw_gives_same_result(self):
        body_cw, fi_cw = split_body_profile(_rect_profile(30, 100, ccw=False))
        body_ccw, fi_ccw = split_body_profile(_rect_profile(30, 100, ccw=True))
        outer_cw = body_cw[:fi_cw + 1]
        outer_ccw = body_ccw[:fi_ccw + 1]
        assert max(p[0] for p in outer_cw) == 30
        assert max(p[0] for p in outer_ccw) == 30

    def test_sharp_lip_bowl(self):
        path = [
            (20, 50),    # rim (max z, max r)
            (18, 48),    # outer side — radius drops (sharp lip)
            (25, 30),    # belly — radius increases again
            (20, 0.0),   # foot
            (0.0, 0.0),  # axis (outer terminates)
            (0.0, 45),   # floor inner (axis)
        ]
        body, foot_idx = split_body_profile(path)
        outer = body[:foot_idx + 1]
        assert any(p[0] >= 25 for p in outer)

    def test_realistic_mug(self):
        path = [
            (35, 100),   # rim outer
            (35, 5),     # outer wall bottom
            (30, 0.0),   # foot outer
            (0.0, 0.0),  # base center
            (0.0, 8),    # floor inner
            (30, 8),     # inner wall bottom
            (30, 97),    # inner wall top
            (32, 100),   # rim inner edge
        ]
        body, foot_idx = split_body_profile(path)
        assert body[0] == (35, 100)
        outer = body[:foot_idx + 1]
        assert outer[1] == (35, 5)


class TestFootConcavity:
    def test_foot_ring_doesnt_confuse_classification(self):
        path = [
            (35, 100),   # rim outer
            (35, 10),    # outer wall
            (30, 3),     # foot tuck-in (concavity starts)
            (30, 6),     # foot ring rises (z goes up — concavity)
            (35, 6),     # foot flare
            (20, 0.0),   # base
            (0.0, 0.0),  # axis
            (0.0, 8),    # floor center
            (30, 8),     # inner wall bottom
            (30, 97),    # inner wall top
        ]
        body, foot_idx = split_body_profile(path)
        outer = body[:foot_idx + 1]
        assert outer[1] == (35, 10)


class TestStartPosition:
    def test_path_starting_at_bottom(self):
        path = [
            (0.0, 0.0),
            (0.0, 100),
            (30, 100),
            (30, 0.0),
        ]
        body, _ = split_body_profile(path)
        assert body[0] == (30, 100)

    def test_path_starting_midway(self):
        path = [
            (35, 50),
            (35, 5),
            (0.0, 0.0),
            (0.0, 8),
            (30, 8),
            (30, 97),
            (35, 100),
        ]
        body, _ = split_body_profile(path)
        assert body[0] == (35, 100)


class TestBodyProfileCompleteness:
    def test_body_contains_all_original_points(self):
        """The reordered body profile should contain all original points."""
        path = _rect_profile(30, 100)
        body, _ = split_body_profile(path)
        for pt in path:
            assert pt in body

    def test_body_length_equals_path_length(self):
        """Body profile should have same number of points as input
        (split point appears once, each axis point appears once)."""
        path = [
            (35, 100),
            (35, 5),
            (0.0, 0.0),
            (0.0, 8),
            (30, 8),
            (30, 97),
        ]
        body, _ = split_body_profile(path)
        # outer walk: (35,100)→(35,5)→(0,0) = 3 points
        # inner walk: (35,100)→(30,97)→(30,8)→(0,8) = 4 points
        # body = outer + reversed(inner[1:]) = 3 + 3 = 6
        assert len(body) == len(path)


class TestErrors:
    def test_too_few_points(self):
        with pytest.raises(ValueError, match="at least 3"):
            split_body_profile([(10, 5), (0, 0)])

    def test_never_reaches_axis(self):
        path = [
            (30, 100),
            (30, 0.0),
            (10, 0.0),
            (10, 100),
        ]
        with pytest.raises(ValueError, match="axis"):
            split_body_profile(path)
