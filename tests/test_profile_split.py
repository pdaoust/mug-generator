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


class TestSplitPoint:
    def test_rectangular(self):
        """Split point is at max z, max r."""
        outer, inner = split_body_profile(_rect_profile(30, 100))
        assert outer[0] == (30, 100)
        assert inner[0] == (30, 100)

    def test_flat_lip_picks_outermost(self):
        """Flat lip: multiple points at max z — outermost (max r) is chosen."""
        path = [
            (40, 100),   # outermost rim point
            (35, 100),   # inner rim point (same z)
            (35, 0.0),
            (0.0, 0.0),
            (0.0, 100),
        ]
        outer, inner = split_body_profile(path)
        assert outer[0] == (40, 100)
        assert inner[0] == (40, 100)


class TestOuterInnerClassification:
    def test_rectangular_outer_has_larger_area(self):
        """Outer side traces the large-radius wall, inner traces the axis."""
        outer, inner = split_body_profile(_rect_profile(30, 100))
        # Outer: (30,100) → (30,0) → (0,0) — large radii
        # Inner: (30,100) → (0,100) → (0,0) — small radii (along axis)
        assert outer[-1][0] < 0.1  # ends at axis
        assert inner[-1][0] < 0.1  # ends at axis
        # The outer path should include the full-width wall
        outer_rs = [p[0] for p in outer]
        assert max(outer_rs) == 30

    def test_ccw_gives_same_result(self):
        """CW and CCW winding produce the same outer/inner split."""
        outer_cw, inner_cw = split_body_profile(_rect_profile(30, 100, ccw=False))
        outer_ccw, inner_ccw = split_body_profile(_rect_profile(30, 100, ccw=True))
        # Both should classify the same way (outer has the large-radius wall)
        assert max(p[0] for p in outer_cw) == 30
        assert max(p[0] for p in outer_ccw) == 30

    def test_sharp_lip_bowl(self):
        """Sharp lip where radius decreases immediately on both sides."""
        # Bowl shape: rim at top, radius decreases on both sides immediately
        path = [
            (20, 50),    # rim (max z, max r)
            (18, 48),    # outer side — radius drops (sharp lip)
            (25, 30),    # belly — radius increases again
            (20, 0.0),   # foot
            (0.0, 0.0),  # axis (outer terminates)
            (0.0, 45),   # floor inner (axis)
        ]
        outer, inner = split_body_profile(path)
        # Outer side should be the one with the belly (larger total area)
        assert any(p[0] >= 25 for p in outer)

    def test_realistic_mug(self):
        """Realistic mug cross-section."""
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
        outer, inner = split_body_profile(path)
        assert outer[0] == (35, 100)
        # Outer should trace down the large-radius wall
        assert outer[1] == (35, 5)


class TestFootConcavity:
    def test_foot_ring_doesnt_confuse_classification(self):
        """Foot ring (concavity) on outer side doesn't flip outer/inner."""
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
        outer, inner = split_body_profile(path)
        # Outer should still be correctly classified
        assert outer[1] == (35, 10)


class TestStartPosition:
    def test_path_starting_at_bottom(self):
        """Path starts at the base, not the rim."""
        # Same rectangle, rotated starting point
        path = [
            (0.0, 0.0),  # start at axis
            (0.0, 100),  # up to inner rim
            (30, 100),   # across rim
            (30, 0.0),   # down outer wall
        ]
        outer, inner = split_body_profile(path)
        assert outer[0] == (30, 100)

    def test_path_starting_midway(self):
        """Path starts in the middle of the outer wall."""
        path = [
            (35, 50),    # midway down outer wall
            (35, 5),     # bottom of outer wall
            (0.0, 0.0),  # axis
            (0.0, 8),    # floor
            (30, 8),     # inner wall bottom
            (30, 97),    # inner wall top
            (35, 100),   # rim
        ]
        outer, inner = split_body_profile(path)
        assert outer[0] == (35, 100)


class TestErrors:
    def test_too_few_points(self):
        with pytest.raises(ValueError, match="at least 3"):
            split_body_profile([(10, 5), (0, 0)])

    def test_never_reaches_axis(self):
        """Profile that never reaches r=0 should raise."""
        path = [
            (30, 100),
            (30, 0.0),
            (10, 0.0),   # doesn't reach axis
            (10, 100),
        ]
        with pytest.raises(ValueError, match="axis"):
            split_body_profile(path)
