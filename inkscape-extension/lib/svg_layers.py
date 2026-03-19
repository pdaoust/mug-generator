"""SVG layer discovery and path extraction.

Uses the inkex API (1.2+) for path parsing and transform composition.
Falls back to xml.etree for basic operation without inkex.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from typing import Optional

# SVG/Inkscape namespaces
SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"

# Try to import inkex for full path support
try:
    import inkex
    HAS_INKEX = True
except ImportError:
    HAS_INKEX = False


def _normalize_label(label: str) -> str:
    """Normalize a layer label for case-insensitive, whitespace-tolerant matching."""
    return re.sub(r'\s+', ' ', label.strip().lower())


def find_layer(svg_root, label: str):
    """Find a layer (SVG group) by its inkscape:label.

    Args:
        svg_root: The SVG root element (etree or inkex).
        label: Layer label to find (case-insensitive, whitespace-tolerant).

    Returns:
        The matching layer element, or None.
    """
    target = _normalize_label(label)

    for elem in svg_root.iter():
        tag = elem.tag if isinstance(elem.tag, str) else ""
        if not tag.endswith("}g") and tag != "g":
            continue

        # Check inkscape:label
        elem_label = elem.get(f"{{{INKSCAPE_NS}}}label", "")
        if _normalize_label(elem_label) == target:
            return elem

        # Also check inkscape:label without namespace (some SVGs)
        elem_label = elem.get("inkscape:label", "")
        if _normalize_label(elem_label) == target:
            return elem

    return None


def _de_casteljau(p0, p1, p2, p3, n_segments=16, max_seg_len=None):
    """Subdivide a cubic Bezier curve into line segments.

    If *max_seg_len* is given, the number of segments is computed from
    the estimated arc length so that each chord is ≈ max_seg_len.
    """
    if max_seg_len is not None and max_seg_len > 0:
        # Control-polygon length is an upper bound on the arc length
        poly_len = (math.hypot(p1[0] - p0[0], p1[1] - p0[1])
                    + math.hypot(p2[0] - p1[0], p2[1] - p1[1])
                    + math.hypot(p3[0] - p2[0], p3[1] - p2[1]))
        n_segments = max(1, round(poly_len / max_seg_len))

    points = []
    for i in range(n_segments + 1):
        t = i / n_segments
        s = 1 - t
        x = s**3 * p0[0] + 3*s**2*t * p1[0] + 3*s*t**2 * p2[0] + t**3 * p3[0]
        y = s**3 * p0[1] + 3*s**2*t * p1[1] + 3*s*t**2 * p2[1] + t**3 * p3[1]
        points.append((x, y))
    return points


def _arc_to_points(cx_start, cy_start, rx, ry, x_rot, large_arc, sweep, cx_end, cy_end,
                    n_segments=16, max_seg_len=None):
    """Convert an SVG arc to line segments.

    Uses the endpoint-to-center parameterization conversion.
    If *max_seg_len* is given, the segment count is derived from the
    arc length.
    """
    if abs(rx) < 1e-12 or abs(ry) < 1e-12:
        return [(cx_end, cy_end)]

    cos_rot = math.cos(math.radians(x_rot))
    sin_rot = math.sin(math.radians(x_rot))

    dx = (cx_start - cx_end) / 2
    dy = (cy_start - cy_end) / 2
    x1p = cos_rot * dx + sin_rot * dy
    y1p = -sin_rot * dx + cos_rot * dy

    rx = abs(rx)
    ry = abs(ry)

    # Scale radii if needed
    lam = (x1p**2 / rx**2) + (y1p**2 / ry**2)
    if lam > 1:
        scale = math.sqrt(lam)
        rx *= scale
        ry *= scale

    num = rx**2 * ry**2 - rx**2 * y1p**2 - ry**2 * x1p**2
    den = rx**2 * y1p**2 + ry**2 * x1p**2
    if den < 1e-12:
        return [(cx_end, cy_end)]

    sq = max(0, num / den)
    root = math.sqrt(sq)
    if large_arc == sweep:
        root = -root

    cxp = root * rx * y1p / ry
    cyp = -root * ry * x1p / rx

    cx_center = cos_rot * cxp - sin_rot * cyp + (cx_start + cx_end) / 2
    cy_center = sin_rot * cxp + cos_rot * cyp + (cy_start + cy_end) / 2

    def angle(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        cross = ux * vy - uy * vx
        return math.atan2(cross, dot)

    theta1 = angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dtheta = angle(
        (x1p - cxp) / rx, (y1p - cyp) / ry,
        (-x1p - cxp) / rx, (-y1p - cyp) / ry
    )

    if sweep and dtheta < 0:
        dtheta += 2 * math.pi
    elif not sweep and dtheta > 0:
        dtheta -= 2 * math.pi

    if max_seg_len is not None and max_seg_len > 0:
        arc_len = abs(dtheta) * (rx + ry) / 2
        n_segments = max(1, round(arc_len / max_seg_len))

    points = []
    for i in range(1, n_segments + 1):
        t = i / n_segments
        theta = theta1 + t * dtheta
        x = rx * math.cos(theta)
        y = ry * math.sin(theta)
        xr = cos_rot * x - sin_rot * y + cx_center
        yr = sin_rot * x + cos_rot * y + cy_center
        points.append((xr, yr))

    return points


def _parse_path_d(d: str, max_seg_len: float | None = None) -> list[tuple[float, float]]:
    """Parse an SVG path 'd' attribute into a polyline.

    Handles M, L, C, A, Z commands (absolute and relative).
    Cubic beziers are subdivided via De Casteljau.

    If *max_seg_len* is given (in SVG user units), bezier and arc
    subdivision density is computed from the curve length so that
    each chord is ≈ max_seg_len.  Line segments are unaffected.
    """
    if not d:
        return []

    # Tokenize: split into commands and numbers
    tokens = re.findall(r'[MLHVCSQTAZmlhvcsqtaz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?', d)

    points = []
    current = (0.0, 0.0)
    start = (0.0, 0.0)
    i = 0

    def next_float():
        nonlocal i
        i += 1
        return float(tokens[i - 1])

    while i < len(tokens):
        cmd = tokens[i]
        i += 1

        if cmd in ('M', 'm'):
            x, y = next_float(), next_float()
            if cmd == 'm':
                x += current[0]
                y += current[1]
            current = (x, y)
            start = current
            points.append(current)
            # Additional coordinate pairs are implicit LineTo
            while i < len(tokens) and tokens[i] not in 'MLHVCSQTAZmlhvcsqtaz':
                x, y = next_float(), next_float()
                if cmd == 'm':
                    x += current[0]
                    y += current[1]
                current = (x, y)
                points.append(current)

        elif cmd in ('L', 'l'):
            while i < len(tokens) and tokens[i] not in 'MLHVCSQTAZmlhvcsqtaz':
                x, y = next_float(), next_float()
                if cmd == 'l':
                    x += current[0]
                    y += current[1]
                current = (x, y)
                points.append(current)

        elif cmd in ('H', 'h'):
            while i < len(tokens) and tokens[i] not in 'MLHVCSQTAZmlhvcsqtaz':
                x = next_float()
                if cmd == 'h':
                    x += current[0]
                current = (x, current[1])
                points.append(current)

        elif cmd in ('V', 'v'):
            while i < len(tokens) and tokens[i] not in 'MLHVCSQTAZmlhvcsqtaz':
                y = next_float()
                if cmd == 'v':
                    y += current[1]
                current = (current[0], y)
                points.append(current)

        elif cmd in ('C', 'c'):
            while i < len(tokens) and tokens[i] not in 'MLHVCSQTAZmlhvcsqtaz':
                x1, y1 = next_float(), next_float()
                x2, y2 = next_float(), next_float()
                x, y = next_float(), next_float()
                if cmd == 'c':
                    x1 += current[0]; y1 += current[1]
                    x2 += current[0]; y2 += current[1]
                    x += current[0]; y += current[1]
                bez = _de_casteljau(current, (x1, y1), (x2, y2), (x, y), max_seg_len=max_seg_len)
                points.extend(bez[1:])  # skip first (= current)
                current = (x, y)

        elif cmd in ('S', 's'):
            while i < len(tokens) and tokens[i] not in 'MLHVCSQTAZmlhvcsqtaz':
                x2, y2 = next_float(), next_float()
                x, y = next_float(), next_float()
                if cmd == 's':
                    x2 += current[0]; y2 += current[1]
                    x += current[0]; y += current[1]
                # Reflect previous control point
                x1 = 2 * current[0] - x2
                y1 = 2 * current[1] - y2
                bez = _de_casteljau(current, (x1, y1), (x2, y2), (x, y), max_seg_len=max_seg_len)
                points.extend(bez[1:])
                current = (x, y)

        elif cmd in ('Q', 'q'):
            while i < len(tokens) and tokens[i] not in 'MLHVCSQTAZmlhvcsqtaz':
                x1, y1 = next_float(), next_float()
                x, y = next_float(), next_float()
                if cmd == 'q':
                    x1 += current[0]; y1 += current[1]
                    x += current[0]; y += current[1]
                # Convert quadratic to cubic
                cp1 = (current[0] + 2/3 * (x1 - current[0]), current[1] + 2/3 * (y1 - current[1]))
                cp2 = (x + 2/3 * (x1 - x), y + 2/3 * (y1 - y))
                bez = _de_casteljau(current, cp1, cp2, (x, y), max_seg_len=max_seg_len)
                points.extend(bez[1:])
                current = (x, y)

        elif cmd in ('T', 't'):
            while i < len(tokens) and tokens[i] not in 'MLHVCSQTAZmlhvcsqtaz':
                x, y = next_float(), next_float()
                if cmd == 't':
                    x += current[0]; y += current[1]
                # No previous Q control point tracking — treat as line
                current = (x, y)
                points.append(current)

        elif cmd in ('A', 'a'):
            while i < len(tokens) and tokens[i] not in 'MLHVCSQTAZmlhvcsqtaz':
                rx_val = next_float()
                ry_val = next_float()
                x_rot = next_float()
                large_arc = int(next_float())
                sweep = int(next_float())
                x, y = next_float(), next_float()
                if cmd == 'a':
                    x += current[0]; y += current[1]
                arc_pts = _arc_to_points(
                    current[0], current[1], rx_val, ry_val,
                    x_rot, large_arc, sweep, x, y,
                    max_seg_len=max_seg_len,
                )
                points.extend(arc_pts)
                current = (x, y)

        elif cmd in ('Z', 'z'):
            current = start

    return points


def _apply_transform_2x3(points, matrix):
    """Apply a 2x3 affine transform matrix to a list of 2D points.

    Matrix is [[a,c,e],[b,d,f]] such that:
    x' = a*x + c*y + e
    y' = b*x + d*y + f
    """
    a, c, e = matrix[0]
    b, d, f = matrix[1]
    return [(a * x + c * y + e, b * x + d * y + f) for x, y in points]


def _parse_transform(transform_str: str) -> list[list[float]]:
    """Parse SVG transform attribute into a 2x3 matrix."""
    if not transform_str:
        return [[1, 0, 0], [0, 1, 0]]

    result = [[1, 0, 0], [0, 1, 0]]

    def multiply(m1, m2):
        """Multiply two 2x3 matrices."""
        return [
            [
                m1[0][0]*m2[0][0] + m1[0][1]*m2[1][0],
                m1[0][0]*m2[0][1] + m1[0][1]*m2[1][1],
                m1[0][0]*m2[0][2] + m1[0][1]*m2[1][2] + m1[0][2],
            ],
            [
                m1[1][0]*m2[0][0] + m1[1][1]*m2[1][0],
                m1[1][0]*m2[0][1] + m1[1][1]*m2[1][1],
                m1[1][0]*m2[0][2] + m1[1][1]*m2[1][2] + m1[1][2],
            ],
        ]

    transforms = re.findall(r'(\w+)\s*\(([^)]*)\)', transform_str)
    for name, args_str in transforms:
        vals = [float(x) for x in re.findall(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?', args_str)]

        if name == 'matrix' and len(vals) == 6:
            m = [[vals[0], vals[2], vals[4]], [vals[1], vals[3], vals[5]]]
        elif name == 'translate':
            tx = vals[0] if vals else 0
            ty = vals[1] if len(vals) > 1 else 0
            m = [[1, 0, tx], [0, 1, ty]]
        elif name == 'scale':
            sx = vals[0] if vals else 1
            sy = vals[1] if len(vals) > 1 else sx
            m = [[sx, 0, 0], [0, sy, 0]]
        elif name == 'rotate':
            angle = math.radians(vals[0]) if vals else 0
            cx_r = vals[1] if len(vals) > 1 else 0
            cy_r = vals[2] if len(vals) > 2 else 0
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)
            # translate(cx,cy) * rotate(a) * translate(-cx,-cy)
            m = [
                [cos_a, -sin_a, cx_r * (1 - cos_a) + cy_r * sin_a],
                [sin_a, cos_a, cy_r * (1 - cos_a) - cx_r * sin_a],
            ]
        else:
            continue

        result = multiply(result, m)

    return result


def _get_composed_transform(elem, root) -> list[list[float]]:
    """Get the composed transform from root to elem.

    Walks up the tree by building a parent map.
    """
    # Build parent map
    parent_map = {}
    for parent in root.iter():
        for child in parent:
            parent_map[child] = parent

    # Collect transforms from elem to root
    transforms = []
    node = elem
    while node is not None and node is not root:
        t = node.get("transform", "")
        if t:
            transforms.append(_parse_transform(t))
        node = parent_map.get(node)

    # Also check root transform
    t = root.get("transform", "")
    if t:
        transforms.append(_parse_transform(t))

    # Compose from root to elem (reverse order)
    result = [[1, 0, 0], [0, 1, 0]]
    for m in reversed(transforms):
        # Multiply result * m
        result = [
            [
                result[0][0]*m[0][0] + result[0][1]*m[1][0],
                result[0][0]*m[0][1] + result[0][1]*m[1][1],
                result[0][0]*m[0][2] + result[0][1]*m[1][2] + result[0][2],
            ],
            [
                result[1][0]*m[0][0] + result[1][1]*m[1][0],
                result[1][0]*m[0][1] + result[1][1]*m[1][1],
                result[1][0]*m[0][2] + result[1][1]*m[1][2] + result[1][2],
            ],
        ]

    return result


def _split_subpath_d(d: str) -> list[str]:
    """Split an SVG path 'd' attribute into subpath strings at M/m boundaries.

    Each returned string starts with an absolute M command.  Relative 'm'
    after a Z/z is converted to absolute using the previous subpath's start
    point.
    """
    tokens = re.findall(
        r'[MLHVCSQTAZmlhvcsqtaz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?', d
    )
    if not tokens:
        return []

    chunks: list[list[str]] = []
    current_chunk: list[str] = []
    prev_start: tuple[float, float] | None = None
    i = 0

    while i < len(tokens):
        tok = tokens[i]
        if tok in ('M', 'm') and current_chunk:
            # End previous chunk, record its start point
            prev_start = _extract_start(current_chunk)
            chunks.append(current_chunk)
            current_chunk = []
            # Convert relative 'm' to absolute 'M' using previous start
            if tok == 'm' and prev_start is not None:
                current_chunk.append('M')
                i += 1
                # Read the first coordinate pair and make absolute
                if i + 1 < len(tokens):
                    x = float(tokens[i]) + prev_start[0]
                    y = float(tokens[i + 1]) + prev_start[1]
                    current_chunk.append(str(x))
                    current_chunk.append(str(y))
                    i += 2
                continue
            else:
                current_chunk.append(tok)
                i += 1
                continue
        current_chunk.append(tok)
        i += 1

    if current_chunk:
        chunks.append(current_chunk)

    return [' '.join(c) for c in chunks]


def _extract_start(chunk_tokens: list[str]) -> tuple[float, float]:
    """Extract the start point (first M/m coordinates) from a token list."""
    for i, tok in enumerate(chunk_tokens):
        if tok in ('M', 'm') and i + 2 < len(chunk_tokens):
            return (float(chunk_tokens[i + 1]), float(chunk_tokens[i + 2]))
    return (0.0, 0.0)


def get_layer_mark_polygons(
    svg_root, label: str, max_seg_len: float | None = None
) -> list[list[tuple[float, float]]]:
    """Extract mark polygons from a named layer, splitting compound paths.

    Each <path> element's 'd' attribute is split at M/m boundaries so that
    compound shapes (e.g. letters with holes) become separate polygons.

    Args:
        svg_root: SVG root element.
        label: Layer label to search for.
        max_seg_len: Bezier/arc subdivision chord length (SVG user units).

    Returns:
        List of polygons (each a list of (x, y) tuples).
        Returns an empty list if the layer doesn't exist (no exception).
    """
    layer = find_layer(svg_root, label)
    if layer is None:
        return []

    polygons: list[list[tuple[float, float]]] = []
    ns_path = f"{{{SVG_NS}}}path"

    for elem in layer.iter():
        tag = elem.tag if isinstance(elem.tag, str) else ""
        if tag != ns_path and tag != "path":
            continue

        d = elem.get("d", "")
        if not d:
            continue

        transform = _get_composed_transform(elem, svg_root)
        subpaths = _split_subpath_d(d)

        for sub_d in subpaths:
            raw_points = _parse_path_d(sub_d, max_seg_len=max_seg_len)
            if len(raw_points) < 3:
                continue
            transformed = _apply_transform_2x3(raw_points, transform)
            polygons.append(transformed)

    return polygons


def get_layer_paths(svg_root, label: str, max_seg_len: float | None = None) -> list[list[tuple[float, float]]]:
    """Extract all paths from a named layer as polylines.

    Args:
        svg_root: SVG root element.
        label: Layer label to search for.
        max_seg_len: If given (in SVG user units), bezier and arc curves
            are subdivided so each chord ≈ this length.  Line segments
            are unaffected.  Defaults to 16 fixed segments per curve.

    Returns:
        List of polylines, each a list of (x, y) tuples in document coordinates.

    Raises:
        ValueError: If the layer is not found.
    """
    layer = find_layer(svg_root, label)
    if layer is None:
        raise ValueError(
            f"Layer '{label}' not found. Check that the layer exists and has "
            f"the correct inkscape:label attribute."
        )

    paths = []
    ns_path = f"{{{SVG_NS}}}path"

    for elem in layer.iter():
        tag = elem.tag if isinstance(elem.tag, str) else ""
        if tag == ns_path or tag == "path":
            d = elem.get("d", "")
            if not d:
                continue

            raw_points = _parse_path_d(d, max_seg_len=max_seg_len)
            if not raw_points:
                continue

            # Apply composed transform
            transform = _get_composed_transform(elem, svg_root)
            transformed = _apply_transform_2x3(raw_points, transform)
            paths.append(transformed)

    return paths


def offset_polygon(
    poly: list[tuple[float, float]], delta: float
) -> list[tuple[float, float]]:
    """Compute a miter-offset polygon.

    Positive *delta* always expands outward regardless of winding
    direction (CCW or CW).  Miter spikes at very acute vertices are
    clamped.
    """
    n = len(poly)
    if n < 3:
        return list(poly)

    # Signed area → winding direction
    signed_area = sum(
        poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1]
        for i in range(n)
    ) / 2.0

    # Left normals (rotate edge 90° CCW) point inward for CCW,
    # outward for CW.  Negate for CCW so positive delta always expands.
    eff = -delta if signed_area > 0 else delta

    result: list[tuple[float, float]] = []
    for i in range(n):
        p_prev = poly[(i - 1) % n]
        p_curr = poly[i]
        p_next = poly[(i + 1) % n]

        ex = (p_curr[0] - p_prev[0], p_curr[1] - p_prev[1])
        fx = (p_next[0] - p_curr[0], p_next[1] - p_curr[1])
        le = math.hypot(*ex)
        lf = math.hypot(*fx)

        if le < 1e-12 or lf < 1e-12:
            result.append(p_curr)
            continue

        ex = (ex[0] / le, ex[1] / le)
        fx = (fx[0] / lf, fx[1] / lf)

        # Left normals
        ne = (-ex[1], ex[0])
        nf = (-fx[1], fx[0])

        bx = ne[0] + nf[0]
        by = ne[1] + nf[1]
        bl = math.hypot(bx, by)

        if bl < 1e-12:
            result.append((p_curr[0] + eff * ne[0], p_curr[1] + eff * ne[1]))
            continue

        bx /= bl
        by /= bl
        cos_half = max(bx * ne[0] + by * ne[1], 0.25)  # clamp spikes
        d = eff / cos_half

        result.append((p_curr[0] + d * bx, p_curr[1] + d * by))

    return result


def _point_in_polygon(point: tuple[float, float],
                      poly: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test."""
    x, y = point
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi) + xi
        ):
            inside = not inside
        j = i
    return inside


def compute_polygon_holes(
    polygons: list[list[tuple[float, float]]],
) -> list[bool]:
    """Determine which polygons are holes using even-odd containment.

    A polygon is a hole if it is contained within an odd number of
    other polygons (tested at its first vertex).
    """
    n = len(polygons)
    result: list[bool] = []
    for i in range(n):
        pt = polygons[i][0]
        count = sum(
            1 for j in range(n)
            if j != i and _point_in_polygon(pt, polygons[j])
        )
        result.append(count % 2 == 1)
    return result
