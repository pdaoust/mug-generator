#!/usr/bin/env python3
"""Mug Generator — Inkscape extension entry point.

Reads artistic guide geometry from named SVG layers and emits raw cubic
Bezier control points (BOSL2 bezpath format) plus user parameters into
OpenSCAD data files.  All polyline tessellation, station generation,
nudging, and volume integration happen at SCAD render time via
``scad/lib/handle_geom.scad``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ext_dir = Path(__file__).resolve().parent
if str(_ext_dir) not in sys.path:
    sys.path.insert(0, str(_ext_dir))

try:
    import inkex
except ImportError:
    sys.exit("inkex module not found. This extension must be run from Inkscape.")

from lib.svg_layers import get_layer_paths_bez, get_layer_mark_bezpaths
from lib.units import to_mm, parse_doc_units, parse_viewbox_bottom, parse_viewbox_scale
from lib.bezier_eval import (
    bezpath_length, bezpath_max_axis, bezpath_min_axis,
    detect_foot_concavity_bez, split_outer_bez_at_rim,
)
from lib.openscad_params import compute_n
from lib.scad_writer import run_all_emitters
from lib.preview import draw_preview


class MugGeneratorEffect(inkex.EffectExtension):
    """Inkscape effect extension for mug generation."""

    def add_arguments(self, pars):
        pars.add_argument("--tab", type=str, default="settings")
        pars.add_argument("--output_dir", type=str, default="")
        pars.add_argument("--fn", type=int, default=0)
        pars.add_argument("--fa", type=float, default=12.0)
        pars.add_argument("--fs", type=float, default=2.0)
        pars.add_argument("--preview", type=inkex.Boolean, default=True)
        pars.add_argument("--plaster_thickness", type=float, default=30.0)
        pars.add_argument("--wall_thickness", type=float, default=0.8)
        pars.add_argument("--alignment_type", type=str, default="natches")
        pars.add_argument("--natch_radius", type=float, default=6.75)
        pars.add_argument("--key_tolerance", type=float, default=0.5)
        pars.add_argument("--filler_tube_height", type=float, default=15.0)
        pars.add_argument("--filler_tube_angle", type=float, default=20.0)
        pars.add_argument("--funnel_wall_angle", type=float, default=30.0)
        pars.add_argument("--funnel_wall", type=float, default=1.5)
        pars.add_argument("--flange_width", type=float, default=3.0)
        pars.add_argument("--breather_hole_dia", type=float, default=1.0)
        pars.add_argument("--breather_hole_count", type=int, default=6)
        pars.add_argument("--clay_shrinkage", type=float, default=10.0)
        pars.add_argument("--mark_depth", type=float, default=1.0)
        pars.add_argument("--mark_inset", type=inkex.Boolean, default=True)
        pars.add_argument("--mark_draft_angle", type=float, default=45.0)
        pars.add_argument("--mark_layer_height", type=float, default=0.20)
        pars.add_argument("--mark_fa", type=float, default=12.0)
        pars.add_argument("--mark_fs", type=float, default=0.25)
        pars.add_argument("--rib_thickness", type=float, default=2.0)
        pars.add_argument("--rib_taper", type=float, default=10.0)
        pars.add_argument("--rib_margin", type=float, default=10.0)
        pars.add_argument("--wheel_direction", type=str, default="counterclockwise")
        pars.add_argument("--hump_rib_direction", type=str, default="top")
        pars.add_argument("--export_prototype", type=inkex.Boolean, default=True)
        pars.add_argument("--export_case_mould", type=inkex.Boolean, default=True)
        pars.add_argument("--export_case_mould_efficient", type=inkex.Boolean, default=True)
        pars.add_argument("--export_funnel", type=inkex.Boolean, default=True)
        pars.add_argument("--export_slump_mould", type=inkex.Boolean, default=True)
        pars.add_argument("--export_slump_rib", type=inkex.Boolean, default=True)
        pars.add_argument("--export_hump_mould", type=inkex.Boolean, default=True)
        pars.add_argument("--export_hump_rib", type=inkex.Boolean, default=True)

    def effect(self):
        svg = self.svg

        output_dir = self.options.output_dir
        if not output_dir:
            inkex.errormsg("Please specify an output directory.")
            return

        plaster = self.options.plaster_thickness
        natch_r = self.options.natch_radius
        if plaster - natch_r * 2 < 10:
            inkex.errormsg(
                f"Plaster thickness ({plaster} mm) minus natch hole diameter "
                f"({natch_r * 2} mm) must be at least 10 mm."
            )
            return

        doc_units = parse_doc_units(svg)
        scale = parse_viewbox_scale(svg, doc_units)
        vb_bottom = parse_viewbox_bottom(svg)

        def svg_to_mm(points):
            return [
                (to_mm(p[0] * scale, doc_units),
                 to_mm((vb_bottom - p[1]) * scale, doc_units))
                for p in points
            ]

        # --- Body bezpath (required) ---
        try:
            body_layer = get_layer_paths_bez(svg, "mug body")
        except ValueError:
            inkex.errormsg(
                "Layer 'mug body' not found.\n"
                "  Create a layer named exactly 'mug body' containing one closed\n"
                "  cross-section path (outer wall, rim, inner wall, floor)."
            )
            return
        if len(body_layer) != 1:
            inkex.errormsg(
                f"Layer 'mug body' has {len(body_layer)} path(s), expected 1."
            )
            return
        body_bez_raw, body_bez_closed = body_layer[0]
        body_bez_mm = svg_to_mm(body_bez_raw)

        # --- Optional handle bezpaths ---
        handle_enabled = True
        try:
            rail_layer = get_layer_paths_bez(svg, "handle rails")
            side_rail_layer = get_layer_paths_bez(svg, "handle side rails")
            profile_layer = get_layer_paths_bez(svg, "handle profile")
        except ValueError:
            handle_enabled = False

        inner_rail_bez_mm: list = []
        outer_rail_bez_mm: list = []
        side_rail_polyline_mm: list = []
        handle_profile_bez_mm: list = []
        n_stations = 0

        if handle_enabled:
            if len(rail_layer) != 2 or len(side_rail_layer) != 1 or len(profile_layer) != 1:
                inkex.errormsg(
                    "Handle layer counts wrong: 'handle rails' needs 2 paths, "
                    "'handle side rails' and 'handle profile' need 1 each."
                )
                return
            inner_rail_bez_mm = svg_to_mm(rail_layer[0][0])
            outer_rail_bez_mm = svg_to_mm(rail_layer[1][0])
            handle_profile_bez_mm = [
                (p[0], p[1]) for p in profile_layer[0][0]
            ]
            # Side rail is consumed as a 1D width-vs-position polyline.
            side_rail_polyline_mm = [
                (to_mm(p[0] * scale, doc_units),
                 to_mm(p[1] * scale, doc_units))
                for p in side_rail_layer[0][0]
            ]

            # Number of handle stations.  Approximate the midline arc length
            # by averaging the inner and outer rail lengths.
            mid_len = (bezpath_length(inner_rail_bez_mm)
                       + bezpath_length(outer_rail_bez_mm)) / 2
            n_stations = compute_n(
                self.options.fn, self.options.fa, self.options.fs, mid_len
            )

        # --- Maker's mark ---
        mark_raw_bez = get_layer_mark_bezpaths(svg, "mark")
        mark_enabled = len(mark_raw_bez) > 0
        mark_bezpaths: list[list[tuple[float, float]]] = []
        if mark_enabled:
            for bez, _closed in mark_raw_bez:
                mark_bezpaths.append([
                    (-to_mm(p[0] * scale, doc_units),
                     -to_mm(p[1] * scale, doc_units))
                    for p in bez
                ])

        # --- Foot concavity, lip / foot extrema (analytic on bezpath) ---
        outer_bez = split_outer_bez_at_rim(body_bez_mm)
        concavity = detect_foot_concavity_bez(outer_bez)

        lip_pt = bezpath_max_axis(outer_bez, 1)
        foot_pt = bezpath_min_axis(outer_bez, 1)
        z_lip = lip_pt[1]
        lip_r = lip_pt[0]
        z_min = foot_pt[1]

        shrinkage_pct = self.options.clay_shrinkage
        cs = 100.0 / (100.0 - shrinkage_pct) if shrinkage_pct > 0 else 1.0

        mould_params = {
            "alignment_type": self.options.alignment_type,
            "plaster_thickness": self.options.plaster_thickness,
            "wall_thickness": self.options.wall_thickness,
            "natch_radius": self.options.natch_radius,
            "key_tolerance": self.options.key_tolerance,
            "funnel_wall_angle": self.options.funnel_wall_angle,
            "funnel_wall": self.options.funnel_wall,
            "flange_width": self.options.flange_width,
            "breather_hole_dia": self.options.breather_hole_dia,
            "breather_hole_count": self.options.breather_hole_count,
        }

        if concavity or mark_enabled:
            mould_params["mould_type"] = 3
            if concavity:
                mould_params["foot_concavity_z"] = concavity[0]
                mould_params["foot_concavity_radius"] = concavity[1]
        else:
            mould_params["mould_type"] = 2

        needs_base = bool(concavity) or bool(
            mark_enabled and self.options.mark_inset
        )
        mould_params["needs_base"] = needs_base
        mould_params["z_min_scaled"] = z_min * cs
        mould_params["z_lip_scaled"] = z_lip * cs
        mould_params["lip_r_scaled"] = lip_r * cs

        opt = self.options
        exports = {
            "prototype": bool(opt.export_prototype),
            "case_mould": bool(opt.export_case_mould),
            "case_mould_efficient": bool(opt.export_case_mould_efficient),
            "funnel": bool(opt.export_funnel),
            "slump_mould": bool(opt.export_slump_mould),
            "slump_rib": bool(opt.export_slump_mould and opt.export_slump_rib),
            "hump_mould": bool(opt.export_hump_mould),
            "hump_rib": bool(opt.export_hump_mould and opt.export_hump_rib),
        }

        data = {
            "exports": exports,
            "mug_body_profile_bez": [list(p) for p in body_bez_mm],
            "mug_body_profile_closed": body_bez_closed,
            "handle_inner_rail_bez": (
                [list(p) for p in inner_rail_bez_mm] if handle_enabled else None
            ),
            "handle_outer_rail_bez": (
                [list(p) for p in outer_rail_bez_mm] if handle_enabled else None
            ),
            "handle_side_rail_polyline": (
                [list(p) for p in side_rail_polyline_mm] if handle_enabled else None
            ),
            "handle_profile_bez": (
                [list(p) for p in handle_profile_bez_mm] if handle_enabled else None
            ),
            "handle_n_stations": n_stations if handle_enabled else None,
            "mark_bezpaths": mark_bezpaths if mark_enabled else None,
            "mug_params": {
                "fn": self.options.fn,
                "fa": self.options.fa,
                "fs": self.options.fs,
                "axis_x": 0.0,
                "filler_tube_height": self.options.filler_tube_height,
                "filler_tube_angle": self.options.filler_tube_angle,
                "clay_shrinkage_pct": shrinkage_pct,
                "handle_enabled": handle_enabled,
                "mark_enabled": mark_enabled,
                "mark_depth": self.options.mark_depth,
                "mark_inset": self.options.mark_inset,
                "mark_draft_angle": self.options.mark_draft_angle,
                "mark_layer_height": self.options.mark_layer_height,
                "mark_fa": self.options.mark_fa,
                "mark_fs": self.options.mark_fs,
                "rib_thickness": self.options.rib_thickness,
                "rib_taper": self.options.rib_taper,
                "rib_margin": self.options.rib_margin,
                "wheel_direction": self.options.wheel_direction,
                "hump_rib_direction": self.options.hump_rib_direction,
                **mould_params,
            },
        }

        run_all_emitters(data, output_dir)

        if self.options.preview:
            draw_preview(
                svg,
                body_bez_raw,
                inner_rail_bez_mm if handle_enabled else None,
                outer_rail_bez_mm if handle_enabled else None,
                side_rail_layer[0][0] if handle_enabled else None,
                vb_bottom, scale, doc_units,
            )


if __name__ == "__main__":
    MugGeneratorEffect().run()
