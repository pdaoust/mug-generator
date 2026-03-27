"""Split a single closed body profile at the rim into outer and inner halves."""


def split_body_profile(path):
    """Split a closed body profile at the rim.

    The profile is a closed polyline of (r, z) points tracing the full
    cross-section of a vessel (outer wall, over the rim, inner wall, floor).

    Returns (body, foot_idx) where:
      - body: the profile reordered to start at the rim split point,
        outer side first (split → outer wall → foot center → inner wall → rim)
      - foot_idx: index of the foot center (r ≈ 0) point that separates
        the outer side from the inner side

    Algorithm:
      1. Find the split point: vertex with max z, ties broken by max r.
      2. Walk both directions to the first r ≈ 0 point (axis crossing).
      3. Flatten foot concavities via running z_min clamp.
      4. Compute trapezoid area for each direction.
      5. Larger area = outer side.
    """
    if len(path) < 3:
        raise ValueError("Body profile must have at least 3 points")

    AXIS_THRESHOLD = 0.1  # mm — close enough to the axis

    # 1. Find split point
    split_idx = 0
    for i, (r, z) in enumerate(path):
        sr, sz = path[split_idx]
        if z > sz or (z == sz and r > sr):
            split_idx = i

    n = len(path)

    def walk(start, step):
        """Walk from start in the given direction, collecting points up to
        and including the first axis crossing (r < threshold)."""
        pts = [path[start]]
        i = (start + step) % n
        while i != start:
            pt = path[i]
            pts.append(pt)
            if pt[0] < AXIS_THRESHOLD:
                break
            i = (i + step) % n
        else:
            raise ValueError(
                "Closed body profile must reach the axis (r ≈ 0) on both "
                "sides of the rim"
            )
        return pts

    side_a = walk(split_idx, +1)
    side_b = walk(split_idx, -1)

    # 3 & 4. Flatten concavities and compute trapezoid area
    def swept_area(pts):
        """Sum of trapezoid areas with foot-concavity flattening."""
        area = 0.0
        z_min = pts[0][1]
        flattened_z = [pts[0][1]]
        for i in range(1, len(pts)):
            z_min = min(z_min, pts[i][1])
            flattened_z.append(z_min)
        for i in range(len(pts) - 1):
            r1, z1 = pts[i][0], flattened_z[i]
            r2, z2 = pts[i + 1][0], flattened_z[i + 1]
            area += (r1 + r2) / 2.0 * abs(z2 - z1)
        return area

    area_a = swept_area(side_a)
    area_b = swept_area(side_b)

    if area_a >= area_b:
        outer, inner = side_a, side_b
    else:
        outer, inner = side_b, side_a

    # Build reordered profile: outer first, then inner (reversed, skip
    # duplicate split point at inner[0])
    body = list(outer) + list(reversed(inner[1:]))
    foot_idx = len(outer) - 1

    return body, foot_idx
