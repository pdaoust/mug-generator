"""Replicate OpenSCAD's $fn/$fa/$fs resolution logic."""

import math


def compute_n(fn: float, fa: float, fs: float, curve_length: float) -> int:
    """Compute the number of segments for a curve.

    Replicates OpenSCAD's logic:
    - If fn > 0, use fn directly.
    - Otherwise: max(5, ceil(360/fa), ceil(curve_length/fs))

    Args:
        fn: Fixed number of segments (0 means auto).
        fa: Minimum angle per segment in degrees.
        fs: Minimum segment length in mm.
        curve_length: Total arc length of the curve in mm.

    Returns:
        Number of segments (at least 5 when fn=0).
    """
    if fn > 0:
        return max(1, int(fn))

    n_fa = math.ceil(360.0 / fa) if fa > 0 else 5
    n_fs = math.ceil(curve_length / fs) if fs > 0 else 5

    return max(5, n_fa, n_fs)
