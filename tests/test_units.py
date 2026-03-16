"""Tests for units.py."""

import math
import xml.etree.ElementTree as ET

import pytest

from lib.units import to_mm, parse_doc_units, parse_viewbox_bottom, parse_viewbox_scale


class TestToMm:
    def test_mm_identity(self):
        assert to_mm(10.0, "mm") == 10.0

    def test_cm(self):
        assert to_mm(1.0, "cm") == 10.0

    def test_inches(self):
        assert to_mm(1.0, "in") == 25.4

    def test_px(self):
        assert to_mm(96.0, "px") == pytest.approx(25.4)

    def test_pt(self):
        assert to_mm(72.0, "pt") == pytest.approx(25.4)

    def test_pc(self):
        assert to_mm(6.0, "pc") == pytest.approx(25.4)

    def test_case_insensitive(self):
        assert to_mm(1.0, " MM ") == 1.0

    def test_unknown_unit_raises(self):
        with pytest.raises(ValueError, match="Unknown unit"):
            to_mm(1.0, "furlongs")


class TestParseDocUnits:
    def test_inkscape_named_view(self):
        svg = ET.fromstring(
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<sodipodi:namedview xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.0.dtd"'
            ' xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"'
            ' inkscape:document-units="mm" />'
            '</svg>'
        )
        assert parse_doc_units(svg) == "mm"

    def test_width_suffix_fallback(self):
        svg = ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg" width="100cm" height="50cm" />')
        assert parse_doc_units(svg) == "cm"

    def test_default_px(self):
        svg = ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50" />')
        assert parse_doc_units(svg) == "px"


class TestParseViewboxBottom:
    def test_viewbox_present(self):
        svg = ET.fromstring(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 10 400 200" />'
        )
        assert parse_viewbox_bottom(svg) == pytest.approx(210.0)

    def test_viewbox_origin_zero(self):
        svg = ET.fromstring(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300" />'
        )
        assert parse_viewbox_bottom(svg) == pytest.approx(300.0)

    def test_height_fallback(self):
        svg = ET.fromstring(
            '<svg xmlns="http://www.w3.org/2000/svg" width="400mm" height="250mm" />'
        )
        assert parse_viewbox_bottom(svg) == pytest.approx(250.0)

    def test_no_viewbox_no_height(self):
        svg = ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg" />')
        assert parse_viewbox_bottom(svg) == 0.0

    def test_comma_separated_viewbox(self):
        svg = ET.fromstring(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0,0,400,200" />'
        )
        assert parse_viewbox_bottom(svg) == pytest.approx(200.0)


class TestParseViewboxScale:
    def test_with_viewbox_and_width(self):
        svg = ET.fromstring(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="200mm" height="100mm" viewBox="0 0 400 200" />'
        )
        scale = parse_viewbox_scale(svg, "mm")
        assert scale == pytest.approx(0.5)

    def test_no_viewbox(self):
        svg = ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="50mm" />')
        scale = parse_viewbox_scale(svg, "mm")
        assert scale == 1.0

    def test_comma_separated_viewbox(self):
        svg = ET.fromstring(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="100mm" height="100mm" viewBox="0,0,100,100" />'
        )
        scale = parse_viewbox_scale(svg, "mm")
        assert scale == pytest.approx(1.0)
