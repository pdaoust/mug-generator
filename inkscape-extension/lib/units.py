"""SVG unit conversion utilities."""

_UNIT_TO_MM = {
    "mm": 1.0,
    "cm": 10.0,
    "in": 25.4,
    "px": 25.4 / 96.0,
    "pt": 25.4 / 72.0,
    "pc": 25.4 / 6.0,
}


def to_mm(value: float, doc_units: str) -> float:
    """Convert a value from document units to millimeters."""
    units = doc_units.strip().lower()
    if units not in _UNIT_TO_MM:
        raise ValueError(f"Unknown unit '{doc_units}'. Supported: {', '.join(sorted(_UNIT_TO_MM))}")
    return value * _UNIT_TO_MM[units]


def parse_doc_units(svg_root) -> str:
    """Determine document units from an SVG root element.

    Checks inkscape:document-units first, then the width attribute's suffix,
    then defaults to 'px'.
    """
    # Check Inkscape namespace attribute
    ns = "{http://www.inkscape.org/namespaces/inkscape}"
    named_view = svg_root.find(f".//{{{ns[1:-1]}}}namedview".replace(ns, ""))
    # Try sodipodi:namedview with inkscape:document-units
    for child in svg_root:
        tag = child.tag if isinstance(child.tag, str) else ""
        if "namedview" in tag:
            doc_units = child.get(f"{ns}document-units")
            if doc_units:
                return doc_units.strip().lower()

    # Fall back to width attribute suffix
    width = svg_root.get("width", "")
    for unit in sorted(_UNIT_TO_MM.keys(), key=len, reverse=True):
        if width.rstrip().endswith(unit):
            return unit

    return "px"


def parse_viewbox_bottom(svg_root) -> float:
    """Return the bottom Y coordinate of the viewBox in SVG user units.

    This is viewBox_y + viewBox_height.  If no viewBox is present,
    falls back to the numeric part of the 'height' attribute, or 0.
    """
    viewbox = svg_root.get("viewBox")
    if viewbox:
        parts = viewbox.replace(",", " ").split()
        if len(parts) == 4:
            return float(parts[1]) + float(parts[3])

    height_attr = svg_root.get("height", "")
    numeric = ""
    for ch in height_attr.strip():
        if ch in "0123456789.+-eE":
            numeric += ch
        else:
            break
    return float(numeric) if numeric else 0.0


def parse_viewbox_scale(svg_root, doc_units: str) -> float:
    """Compute the scale factor from SVG user units to doc_units.

    Returns the multiplier such that: svg_user_unit * scale = value_in_doc_units.
    If there is no viewBox, returns the conversion factor for the doc_units
    assuming 1 user unit = 1 doc_unit.
    """
    viewbox = svg_root.get("viewBox")
    width_attr = svg_root.get("width")

    if viewbox and width_attr:
        parts = viewbox.replace(",", " ").split()
        if len(parts) == 4:
            vb_width = float(parts[2])
            # Strip unit from width attribute to get the numeric part
            width_str = width_attr.strip()
            numeric = ""
            for i, ch in enumerate(width_str):
                if ch in "0123456789.+-eE":
                    numeric += ch
                else:
                    break
            if numeric:
                doc_width = float(numeric)
                return doc_width / vb_width

    return 1.0
