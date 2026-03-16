"""SVG preview layer for mug generator output.

Draws a semi-transparent preview of the mug body silhouette and handle
footprint into a scratch layer in the SVG document.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .rail_sampler import Station

# Inkscape/SVG namespaces
SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"

PREVIEW_LABEL = "_preview"
PREVIEW_STYLE = "fill:magenta;fill-opacity:0.3;stroke:magenta;stroke-width:0.5;stroke-opacity:0.6"
INDICATOR_STYLE = "fill:none;stroke:red;stroke-width:1;stroke-opacity:0.8"


def _get_etree():
    """Return the appropriate ElementTree module — lxml if inkex is loaded, else stdlib."""
    try:
        from lxml import etree
        return etree
    except ImportError:
        import xml.etree.ElementTree as ET
        return ET


def _find_or_create_preview_layer(svg):
    """Find or create the _preview scratch layer, clearing any existing content."""
    etree = _get_etree()

    for layer in svg.findall(f".//{{{SVG_NS}}}g"):
        label = layer.get(f"{{{INKSCAPE_NS}}}label", "")
        if label == PREVIEW_LABEL:
            for child in list(layer):
                layer.remove(child)
            return layer

    # Create new layer using the same element type as the svg tree
    layer = etree.SubElement(svg, f"{{{SVG_NS}}}g")
    layer.set(f"{{{INKSCAPE_NS}}}label", PREVIEW_LABEL)
    layer.set(f"{{{INKSCAPE_NS}}}groupmode", "layer")
    return layer


def _add_path(layer, d: str, style: str) -> None:
    """Add a path element to a layer, using whatever etree the layer belongs to."""
    etree = _get_etree()
    path_elem = etree.SubElement(layer, f"{{{SVG_NS}}}path")
    path_elem.set("d", d)
    path_elem.set("style", style)


def _points_to_path_d(points: list[tuple[float, float]]) -> str:
    """Convert a list of (x, y) points to an SVG path 'd' attribute."""
    if not points:
        return ""
    parts = [f"M {points[0][0]:.4f},{points[0][1]:.4f}"]
    for p in points[1:]:
        parts.append(f"L {p[0]:.4f},{p[1]:.4f}")
    parts.append("Z")
    return " ".join(parts)


def draw_preview(
    svg,
    mug_profile_mm: list[tuple[float, float]],
    stations: list["Station"],
    handle_stations_3d: list[list[tuple[float, float, float]]],
) -> None:
    """Draw preview geometry into the _preview layer.

    All coordinates are in SVG user units (mm with Y already inverted for SVG).

    Args:
        svg: SVG root element.
        mug_profile_mm: Mug profile as [(x_mm, z_mm), ...] in document coords.
        stations: Sampled handle stations.
        handle_stations_3d: 3D handle cross-section polygons.
    """
    layer = _find_or_create_preview_layer(svg)

    # Mug body silhouette: draw the profile polyline (mirrored for full silhouette)
    if mug_profile_mm:
        right_side = [(p[0], -p[1]) for p in mug_profile_mm]  # un-invert Y back to SVG
        left_side = [(-p[0] + 2 * min(pt[0] for pt in mug_profile_mm), -p[1])
                     for p in mug_profile_mm]

        silhouette = right_side + list(reversed(left_side))
        d = _points_to_path_d(silhouette)
        if d:
            _add_path(layer, d, PREVIEW_STYLE)

    # Handle footprint: project 3D cross-sections to XZ plane (SVG X, -Z for SVG Y)
    if handle_stations_3d:
        for poly_3d in [handle_stations_3d[0], handle_stations_3d[-1]]:
            pts_2d = [(p[0], -p[2]) for p in poly_3d]
            d = _points_to_path_d(pts_2d)
            if d:
                _add_path(layer, d, INDICATOR_STYLE)

        # Draw handle path (centroids)
        if stations:
            centroid_pts = [(s.centroid[0], -s.centroid[2]) for s in stations]
            parts = [f"M {centroid_pts[0][0]:.4f},{centroid_pts[0][1]:.4f}"]
            for p in centroid_pts[1:]:
                parts.append(f"L {p[0]:.4f},{p[1]:.4f}")
            d = " ".join(parts)
            _add_path(layer, d, "fill:none;stroke:magenta;stroke-width:0.8;stroke-opacity:0.7")
