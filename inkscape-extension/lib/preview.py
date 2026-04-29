"""SVG preview layer for mug generator output.

Draws a semi-transparent silhouette of the mug body, handle rails, side
rail width, and funnel into a scratch layer in the SVG document.

Stations are no longer drawn here — they only exist post-SCAD-render.
The rails / profile / side-rail geometry uses raw SVG bezier control
polygons (close enough to the curve for a preview).
"""

from __future__ import annotations

SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"

PREVIEW_LABEL = "_preview"
BODY_STYLE = "fill:magenta;fill-opacity:0.3;stroke:magenta;stroke-width:0.5;stroke-opacity:0.6"
RAIL_STYLE = "fill:none;stroke:red;stroke-width:0.8;stroke-opacity:0.6"
SIDE_RAIL_STYLE = "fill:green;fill-opacity:0.3;stroke:green;stroke-width:0.5;stroke-opacity:0.6"
FUNNEL_STYLE = "fill:dodgerblue;fill-opacity:0.3;stroke:dodgerblue;stroke-width:0.5;stroke-opacity:0.6"


def _get_etree():
    try:
        from lxml import etree
        return etree
    except ImportError:
        import xml.etree.ElementTree as ET
        return ET


def _find_or_create_preview_layer(svg):
    etree = _get_etree()

    for layer in svg.findall(f".//{{{SVG_NS}}}g"):
        label = layer.get(f"{{{INKSCAPE_NS}}}label", "")
        if label == PREVIEW_LABEL:
            for child in list(layer):
                layer.remove(child)
            return layer

    layer = etree.SubElement(svg, f"{{{SVG_NS}}}g")
    layer.set(f"{{{INKSCAPE_NS}}}label", PREVIEW_LABEL)
    layer.set(f"{{{INKSCAPE_NS}}}groupmode", "layer")
    return layer


def _add_path(layer, d: str, style: str) -> None:
    etree = _get_etree()
    path_elem = etree.SubElement(layer, f"{{{SVG_NS}}}path")
    path_elem.set("d", d)
    path_elem.set("style", style)


def _points_to_path_d(points, closed=True) -> str:
    if not points:
        return ""
    parts = [f"M {points[0][0]:.4f},{points[0][1]:.4f}"]
    for p in points[1:]:
        parts.append(f"L {p[0]:.4f},{p[1]:.4f}")
    if closed:
        parts.append("Z")
    return " ".join(parts)


def draw_preview(
    svg,
    body_bez_svg,
    inner_rail_mm=None,
    outer_rail_mm=None,
    side_rail_svg=None,
    vb_bottom: float = 0.0,
    scale: float = 1.0,
    doc_units: str = "mm",
) -> None:
    """Draw a mug-body silhouette + handle rails + side rail + funnel hint.

    Geometry is drawn from the raw SVG bezier control polygons — close
    enough for a preview without re-tessellating in Python.
    """
    layer = _find_or_create_preview_layer(svg)

    # Mug body silhouette (right half + mirror) from control polygon.
    if body_bez_svg:
        right_side = list(body_bez_svg)
        left_side = [(-p[0], p[1]) for p in body_bez_svg]
        d = _points_to_path_d(right_side + list(reversed(left_side)))
        if d:
            _add_path(layer, d, BODY_STYLE)

    # Handle rails (mm coords; convert back to SVG y).
    from lib.units import to_mm  # noqa: E402

    def _mm_to_svg_y(z_mm):
        # Inverse of (vb_bottom - svg_y) * scale → mm
        return vb_bottom - (z_mm / to_mm(scale, doc_units))

    for rail in (inner_rail_mm, outer_rail_mm):
        if not rail:
            continue
        pts_svg = [(p[0] / to_mm(scale, doc_units), _mm_to_svg_y(p[1]))
                   for p in rail]
        d = _points_to_path_d(pts_svg, closed=False)
        if d:
            _add_path(layer, d, RAIL_STYLE)

    # Side rail width profile (mirror across x=0).
    if side_rail_svg:
        sorted_rail = sorted(side_rail_svg, key=lambda p: p[1])
        right_edge = [(p[0], p[1]) for p in sorted_rail]
        left_edge = [(-p[0], p[1]) for p in reversed(sorted_rail)]
        d = _points_to_path_d(right_edge + left_edge)
        if d:
            _add_path(layer, d, SIDE_RAIL_STYLE)
