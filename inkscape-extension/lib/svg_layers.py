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


def _subdivide_adaptive(p0, p1, p2, p3, fa_rad, fs, depth, max_depth=12):
    """Recursively subdivide a cubic Bezier until each segment is flat enough.

    Returns a list of points NOT including *p0* (the caller prepends it).

    Stopping criteria (matching OpenSCAD's resolution model):
      - *fs* (min segment length): stop if chord_len ≤ fs.
      - *fa_rad* (min angle, radians): stop if the estimated angular span
        of the segment ≤ fa_rad (approximated as 8·deviation / chord_len).
      - If neither is given, an absolute deviation tolerance of 0.1 is used.
    """
    if depth >= max_depth:
        return [p3]

    dx, dy = p3[0] - p0[0], p3[1] - p0[1]
    chord_len = math.hypot(dx, dy)

    # fs criterion: segment is already short enough
    if fs is not None and chord_len <= fs:
        return [p3]

    if chord_len < 1e-10:
        # Degenerate chord — measure control-point distance from P0
        d = max(math.hypot(p1[0] - p0[0], p1[1] - p0[1]),
                math.hypot(p2[0] - p0[0], p2[1] - p0[1]))
        if d < 1e-10:
            return [p3]
    else:
        # Perpendicular distance from P1 and P2 to chord P0→P3
        d1 = abs(dx * (p0[1] - p1[1]) - dy * (p0[0] - p1[0])) / chord_len
        d2 = abs(dx * (p0[1] - p2[1]) - dy * (p0[0] - p2[0])) / chord_len
        d = max(d1, d2)

        if fa_rad is not None:
            # fa criterion: angular span is small enough
            # θ ≈ 8d/chord_len for a circular arc
            if d <= chord_len * fa_rad / 8:
                return [p3]
        elif fs is None:
            # Absolute fallback when neither fa nor fs is given
            if d <= 0.1:
                return [p3]

    # De Casteljau split at t=0.5
    m01 = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
    m12 = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
    m23 = ((p2[0] + p3[0]) / 2, (p2[1] + p3[1]) / 2)
    m012 = ((m01[0] + m12[0]) / 2, (m01[1] + m12[1]) / 2)
    m123 = ((m12[0] + m23[0]) / 2, (m12[1] + m23[1]) / 2)
    mid = ((m012[0] + m123[0]) / 2, (m012[1] + m123[1]) / 2)

    left = _subdivide_adaptive(p0, m01, m012, mid, fa_rad, fs, depth + 1, max_depth)
    right = _subdivide_adaptive(mid, m123, m23, p3, fa_rad, fs, depth + 1, max_depth)
    return left + right


def _de_casteljau(p0, p1, p2, p3, fa_deg=None, fs=None):
    """Subdivide a cubic Bezier curve via adaptive recursive subdivision.

    Uses OpenSCAD-compatible resolution criteria:

      - *fa_deg* (min angle, degrees): controls how flat each segment must
        be relative to its length.  Derived from ``$fn`` as ``360/$fn``,
        or passed directly as ``$fa``.
      - *fs* (min segment length, user units): prevents over-subdivision
        of short segments.  Passed directly as ``$fs`` (converted to SVG
        user units by the caller).

    When ``$fn`` is used, only *fa_deg* is set (no *fs* floor).
    When neither is given, an absolute deviation tolerance of 0.1 is used.
    """
    fa_rad = math.radians(fa_deg) if fa_deg is not None else None
    return [p0] + _subdivide_adaptive(p0, p1, p2, p3, fa_rad, fs, 0)


def _arc_to_points(cx_start, cy_start, rx, ry, x_rot, large_arc, sweep, cx_end, cy_end,
                    n_segments=16, fa_deg=None, fs=None):
    """Convert an SVG arc to line segments.

    Uses the endpoint-to-center parameterization conversion.
    If *fa_deg* and/or *fs* are given, the segment count is derived
    from them (matching OpenSCAD's resolution model).  Otherwise
    falls back to *n_segments* uniform steps.
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

    if fa_deg is not None or fs is not None:
        n_fa = math.ceil(abs(dtheta) / math.radians(fa_deg)) if fa_deg else 1
        arc_len = abs(dtheta) * (rx + ry) / 2
        n_fs = math.ceil(arc_len / fs) if fs else 1
        n_segments = max(1, n_fa, n_fs)

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


def _parse_path_d(d: str, fa_deg: float | None = None,
                   fs: float | None = None) -> list[tuple[float, float]]:
    """Parse an SVG path 'd' attribute into a polyline.

    Handles M, L, C, A, Z commands (absolute and relative).
    Cubic beziers are subdivided adaptively based on flatness.

    If *fa_deg* (min angle, degrees) and/or *fs* (min segment length,
    SVG user units) are given, bezier and arc subdivision density
    matches OpenSCAD's ``$fa``/``$fs`` resolution model.
    Line segments are unaffected.
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
                bez = _de_casteljau(current, (x1, y1), (x2, y2), (x, y), fa_deg=fa_deg, fs=fs)
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
                bez = _de_casteljau(current, (x1, y1), (x2, y2), (x, y), fa_deg=fa_deg, fs=fs)
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
                bez = _de_casteljau(current, cp1, cp2, (x, y), fa_deg=fa_deg, fs=fs)
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
                    fa_deg=fa_deg, fs=fs,
                )
                points.extend(arc_pts)
                current = (x, y)

        elif cmd in ('Z', 'z'):
            current = start

    return points


def _line_to_bezier(p0: tuple[float, float],
                    p1: tuple[float, float]) -> list[tuple[float, float]]:
    """Encode a straight chord as a cubic Bezier with handles at 1/3 and 2/3.

    Returns three points (c1, c2, knot1) — the caller already has knot0.
    """
    c1 = (p0[0] + (p1[0] - p0[0]) / 3, p0[1] + (p1[1] - p0[1]) / 3)
    c2 = (p0[0] + 2 * (p1[0] - p0[0]) / 3, p0[1] + 2 * (p1[1] - p0[1]) / 3)
    return [c1, c2, p1]


def _path_d_to_bezpath(d: str) -> tuple[list[tuple[float, float]], bool]:
    """Parse an SVG path 'd' attribute into a cubic-Bezier bezpath.

    Output layout matches BOSL2: ``[k0, c0a, c0b, k1, c1a, c1b, k2, ...]``,
    one knot at the start and three points per segment.

    - L/H/V/M-implicit lines are encoded as cubic Beziers with handles
      at 1/3 and 2/3 of the chord (a uniform format avoids special cases
      in the SCAD consumer).
    - Q/T quadratics are converted to cubics via the standard formula.
    - C/S cubics pass through unchanged.
    - A arcs are tessellated to a polyline (via ``_arc_to_points`` with a
      conservative resolution) and each consecutive pair is encoded as a
      straight cubic Bezier — analytic arc-to-cubic conversion is left
      for a later refinement.
    - Z closes the path; the caller gets ``closed=True`` and the returned
      bezpath does **not** repeat the start knot at the end (BOSL2 convention
      for closed bezpaths is to repeat it; we let the consumer add it via
      ``closed`` flag handling).

    Returns:
        (bezpath, closed) — bezpath is a flat list of (x, y) tuples; closed
        is True if the path ends with a Z command.
    """
    if not d:
        return ([], False)

    tokens = re.findall(
        r'[MLHVCSQTAZmlhvcsqtaz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?', d
    )

    bez: list[tuple[float, float]] = []
    current = (0.0, 0.0)
    start = (0.0, 0.0)
    last_cubic_c2: tuple[float, float] | None = None
    last_quad_c1: tuple[float, float] | None = None
    closed = False
    i = 0

    def next_float():
        nonlocal i
        i += 1
        return float(tokens[i - 1])

    def emit_line(target):
        nonlocal current
        bez.extend(_line_to_bezier(current, target))
        current = target

    def emit_cubic(c1, c2, target):
        nonlocal current
        bez.extend([c1, c2, target])
        current = target

    while i < len(tokens):
        cmd = tokens[i]
        i += 1

        if cmd in ('M', 'm'):
            x, y = next_float(), next_float()
            if cmd == 'm':
                x += current[0]; y += current[1]
            current = (x, y)
            start = current
            if not bez:
                bez.append(current)
            else:
                # Subsequent M starts a new subpath; we only support a
                # single subpath per call site here (compound paths are
                # split upstream by _split_subpath_d).
                bez.append(current)
            last_cubic_c2 = None
            last_quad_c1 = None
            # Implicit lineto for additional coordinate pairs
            while i < len(tokens) and tokens[i] not in 'MLHVCSQTAZmlhvcsqtaz':
                x, y = next_float(), next_float()
                if cmd == 'm':
                    x += current[0]; y += current[1]
                emit_line((x, y))
                last_cubic_c2 = None
                last_quad_c1 = None

        elif cmd in ('L', 'l'):
            while i < len(tokens) and tokens[i] not in 'MLHVCSQTAZmlhvcsqtaz':
                x, y = next_float(), next_float()
                if cmd == 'l':
                    x += current[0]; y += current[1]
                emit_line((x, y))
                last_cubic_c2 = None
                last_quad_c1 = None

        elif cmd in ('H', 'h'):
            while i < len(tokens) and tokens[i] not in 'MLHVCSQTAZmlhvcsqtaz':
                x = next_float()
                if cmd == 'h':
                    x += current[0]
                emit_line((x, current[1]))
                last_cubic_c2 = None
                last_quad_c1 = None

        elif cmd in ('V', 'v'):
            while i < len(tokens) and tokens[i] not in 'MLHVCSQTAZmlhvcsqtaz':
                y = next_float()
                if cmd == 'v':
                    y += current[1]
                emit_line((current[0], y))
                last_cubic_c2 = None
                last_quad_c1 = None

        elif cmd in ('C', 'c'):
            while i < len(tokens) and tokens[i] not in 'MLHVCSQTAZmlhvcsqtaz':
                x1, y1 = next_float(), next_float()
                x2, y2 = next_float(), next_float()
                x, y = next_float(), next_float()
                if cmd == 'c':
                    x1 += current[0]; y1 += current[1]
                    x2 += current[0]; y2 += current[1]
                    x += current[0]; y += current[1]
                emit_cubic((x1, y1), (x2, y2), (x, y))
                last_cubic_c2 = (x2, y2)
                last_quad_c1 = None

        elif cmd in ('S', 's'):
            while i < len(tokens) and tokens[i] not in 'MLHVCSQTAZmlhvcsqtaz':
                x2, y2 = next_float(), next_float()
                x, y = next_float(), next_float()
                if cmd == 's':
                    x2 += current[0]; y2 += current[1]
                    x += current[0]; y += current[1]
                if last_cubic_c2 is not None:
                    x1 = 2 * current[0] - last_cubic_c2[0]
                    y1 = 2 * current[1] - last_cubic_c2[1]
                else:
                    x1, y1 = current
                emit_cubic((x1, y1), (x2, y2), (x, y))
                last_cubic_c2 = (x2, y2)
                last_quad_c1 = None

        elif cmd in ('Q', 'q'):
            while i < len(tokens) and tokens[i] not in 'MLHVCSQTAZmlhvcsqtaz':
                qx1, qy1 = next_float(), next_float()
                x, y = next_float(), next_float()
                if cmd == 'q':
                    qx1 += current[0]; qy1 += current[1]
                    x += current[0]; y += current[1]
                # Quadratic → cubic
                cp1 = (current[0] + 2/3 * (qx1 - current[0]),
                       current[1] + 2/3 * (qy1 - current[1]))
                cp2 = (x + 2/3 * (qx1 - x), y + 2/3 * (qy1 - y))
                emit_cubic(cp1, cp2, (x, y))
                last_quad_c1 = (qx1, qy1)
                last_cubic_c2 = None

        elif cmd in ('T', 't'):
            while i < len(tokens) and tokens[i] not in 'MLHVCSQTAZmlhvcsqtaz':
                x, y = next_float(), next_float()
                if cmd == 't':
                    x += current[0]; y += current[1]
                if last_quad_c1 is not None:
                    qx1 = 2 * current[0] - last_quad_c1[0]
                    qy1 = 2 * current[1] - last_quad_c1[1]
                else:
                    qx1, qy1 = current
                cp1 = (current[0] + 2/3 * (qx1 - current[0]),
                       current[1] + 2/3 * (qy1 - current[1]))
                cp2 = (x + 2/3 * (qx1 - x), y + 2/3 * (qy1 - y))
                emit_cubic(cp1, cp2, (x, y))
                last_quad_c1 = (qx1, qy1)
                last_cubic_c2 = None

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
                # Tessellate the arc, then encode each chord as a
                # straight cubic.  Resolution here is decoupled from
                # OpenSCAD's $fa/$fs (rendering happens downstream); use
                # a fixed dense ~3° step so the chord-to-arc error is
                # under 0.04% of the arc radius.
                arc_pts = _arc_to_points(
                    current[0], current[1], rx_val, ry_val,
                    x_rot, large_arc, sweep, x, y,
                    fa_deg=3.0, fs=None,
                )
                for ap in arc_pts:
                    emit_line(ap)
                last_cubic_c2 = None
                last_quad_c1 = None

        elif cmd in ('Z', 'z'):
            closed = True
            # Close back to start with a straight cubic if we haven't
            # already arrived there.
            if (abs(current[0] - start[0]) > 1e-9 or
                    abs(current[1] - start[1]) > 1e-9):
                emit_line(start)
            last_cubic_c2 = None
            last_quad_c1 = None

    return (bez, closed)


def get_layer_paths_bez(
    svg_root, label: str,
) -> list[tuple[list[tuple[float, float]], bool]]:
    """Extract all paths from a named layer as cubic-Bezier bezpaths.

    Returns a list of ``(bezpath, closed)`` tuples in document coordinates,
    with composed transforms applied to every control point.

    Bezpath layout: ``[k0, c0a, c0b, k1, c1a, c1b, k2, ...]`` (cubic, BOSL2
    convention).

    Raises:
        ValueError: If the layer is not found.
    """
    layer = find_layer(svg_root, label)
    if layer is None:
        raise ValueError(
            f"Layer '{label}' not found. Check that the layer exists and has "
            f"the correct inkscape:label attribute."
        )

    out: list[tuple[list[tuple[float, float]], bool]] = []
    ns_path = f"{{{SVG_NS}}}path"

    for elem in layer.iter():
        tag = elem.tag if isinstance(elem.tag, str) else ""
        if tag != ns_path and tag != "path":
            continue

        d = elem.get("d", "")
        if not d:
            continue

        transform = _get_composed_transform(elem, svg_root)

        # Single subpath per element for now (the body profile and the
        # rails/profile/side-rails are all single-subpath).  Compound
        # paths (e.g. marks) need _split_subpath_d-based extraction.
        bez, closed = _path_d_to_bezpath(d)
        if not bez:
            continue
        bez = _apply_transform_2x3(bez, transform)
        out.append((bez, closed))

    return out


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
            # Convert relative 'm' to absolute 'M' using previous start.
            # Insert an explicit 'l' so that any implicit coordinate pairs
            # after the first one are still treated as relative lineto
            # (SVG spec: implicit pairs after 'm' are 'l', not 'L').
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
                    # Any following implicit coords are relative lineto
                    current_chunk.append('l')
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
    svg_root, label: str, fa_deg: float | None = None,
    fs: float | None = None,
) -> list[list[tuple[float, float]]]:
    """Extract mark polygons from a named layer, splitting compound paths.

    Each <path> element's 'd' attribute is split at M/m boundaries so that
    compound shapes (e.g. letters with holes) become separate polygons.

    Args:
        svg_root: SVG root element.
        label: Layer label to search for.
        fa_deg: Min angle per segment (degrees) for curve subdivision.
        fs: Min segment length (SVG user units) for curve subdivision.

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
            raw_points = _parse_path_d(sub_d, fa_deg=fa_deg, fs=fs)
            if len(raw_points) < 3:
                continue
            transformed = _apply_transform_2x3(raw_points, transform)
            polygons.append(transformed)

    return polygons


def get_layer_mark_bezpaths(
    svg_root, label: str,
) -> list[tuple[list[tuple[float, float]], bool]]:
    """Extract mark paths as cubic-Bezier bezpaths, splitting compound paths.

    Each <path>'s 'd' is split at M/m boundaries so compound shapes (e.g.
    letters with holes) become separate bezpaths.  Composed transforms
    are applied to every control point.

    Returns a list of ``(bezpath, closed)`` tuples; empty if the layer
    is missing.
    """
    layer = find_layer(svg_root, label)
    if layer is None:
        return []

    out: list[tuple[list[tuple[float, float]], bool]] = []
    ns_path = f"{{{SVG_NS}}}path"

    for elem in layer.iter():
        tag = elem.tag if isinstance(elem.tag, str) else ""
        if tag != ns_path and tag != "path":
            continue
        d = elem.get("d", "")
        if not d:
            continue
        transform = _get_composed_transform(elem, svg_root)
        for sub_d in _split_subpath_d(d):
            bez, closed = _path_d_to_bezpath(sub_d)
            if not bez:
                continue
            bez = _apply_transform_2x3(bez, transform)
            out.append((bez, closed))

    return out


def get_layer_paths(svg_root, label: str, fa_deg: float | None = None,
                    fs: float | None = None) -> list[list[tuple[float, float]]]:
    """Extract all paths from a named layer as polylines.

    Args:
        svg_root: SVG root element.
        label: Layer label to search for.
        fa_deg: Min angle per segment (degrees) for curve subdivision.
        fs: Min segment length (SVG user units) for curve subdivision.

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

            raw_points = _parse_path_d(d, fa_deg=fa_deg, fs=fs)
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
        cos_half = bx * ne[0] + by * ne[1]

        # Miter limit: if the miter would extend more than 2× delta,
        # fall back to a simple normal offset (no miter).  This
        # prevents spikes at sharp corners in converted text.
        if cos_half < 0.5:
            result.append((p_curr[0] + eff * ne[0], p_curr[1] + eff * ne[1]))
            continue

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
