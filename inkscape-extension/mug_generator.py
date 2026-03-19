#!/usr/bin/env python3
"""Mug Generator — Inkscape extension entry point.

Reads artistic guide geometry from named SVG layers, computes a
four-rail lofted handle and revolved mug body, and emits OpenSCAD
data files plus a static assembly file.
"""

from __future__ import annotations

import sys
from pathlib import Path

# When run by Inkscape, the extension dir is the working directory.
# Ensure lib/ is importable.
_ext_dir = Path(__file__).resolve().parent
if str(_ext_dir) not in sys.path:
    sys.path.insert(0, str(_ext_dir))

try:
    import inkex
except ImportError:
    sys.exit("inkex module not found. This extension must be run from Inkscape.")

from lib.svg_layers import (
    get_layer_paths, get_layer_mark_polygons,
    offset_polygon, compute_polygon_holes,
)
from lib.units import to_mm, parse_doc_units, parse_viewbox_bottom, parse_viewbox_scale
from lib.mug_surface import MugSurface
from lib.openscad_params import compute_n
from lib.rail_sampler import sample_rails
from lib.side_rail_extender import apply_side_rails
from lib.profile_transformer import generate_handle_stations
from lib.scad_writer import run_all_emitters
from lib.preview import draw_preview


class MugGeneratorEffect(inkex.EffectExtension):
    """Inkscape effect extension for mug generation."""

    def add_arguments(self, pars):
        pars.add_argument("--tab", type=str, default="settings")  # notebook tab
        pars.add_argument("--output_dir", type=str, default="")
        pars.add_argument("--fn", type=int, default=0)
        pars.add_argument("--fa", type=float, default=12.0)
        pars.add_argument("--fs", type=float, default=2.0)
        pars.add_argument("--preview", type=inkex.Boolean, default=True)
        pars.add_argument("--plaster_thickness", type=float, default=30.0)
        pars.add_argument("--wall_thickness", type=float, default=0.8)
        pars.add_argument("--natch_radius", type=float, default=6.75)
        pars.add_argument("--funnel_wall_angle", type=float, default=30.0)
        pars.add_argument("--funnel_wall", type=float, default=1.5)
        pars.add_argument("--flange_width", type=float, default=3.0)
        pars.add_argument("--breather_hole_dia", type=float, default=1.0)
        pars.add_argument("--breather_hole_count", type=int, default=6)
        pars.add_argument("--clay_shrinkage", type=float, default=10.0)
        pars.add_argument("--mark_depth", type=float, default=1.0)
        pars.add_argument("--mark_inset", type=inkex.Boolean, default=True)
        pars.add_argument("--mark_draft_angle", type=float, default=45.0)

    def effect(self):
        svg = self.svg

        output_dir = self.options.output_dir
        if not output_dir:
            inkex.errormsg("Please specify an output directory.")
            return

        # Validate mould parameters
        plaster = self.options.plaster_thickness
        natch_r = self.options.natch_radius
        if plaster - natch_r * 2 < 10:
            inkex.errormsg(
                f"Plaster thickness ({plaster} mm) minus natch hole diameter "
                f"({natch_r * 2} mm) must be at least 10 mm."
            )
            return

        # Determine units and scale
        doc_units = parse_doc_units(svg)
        scale = parse_viewbox_scale(svg, doc_units)
        vb_bottom = parse_viewbox_bottom(svg)

        def svg_to_mm(points):
            """Convert SVG user-unit points to mm.

            X passes through directly. Y is flipped so that the bottom
            of the viewBox becomes Z=0 and everything above it is positive Z.
            """
            return [
                (to_mm(p[0] * scale, doc_units),
                 to_mm((vb_bottom - p[1]) * scale, doc_units))
                for p in points
            ]

        # Extract and validate layers
        errors = []
        layers = {}
        expected = {
            "mug body": {
                "min": 2, "max": 2,
                "desc": "outer wall profile and inner wall profile (half-profiles in the XZ plane)",
            },
            "handle rails": {
                "min": 2, "max": 2,
                "desc": "inner rail (near mug) and outer rail (far from mug)",
            },
            "side rails": {
                "min": 1, "max": 1,
                "desc": "one side rail path (X = half-width, Y = position along handle)",
            },
            "handle profile": {
                "min": 1, "max": 1,
                "desc": "one closed path for the handle cross-section shape",
            },
        }

        for label, spec in expected.items():
            try:
                paths = get_layer_paths(svg, label)
            except ValueError:
                errors.append(
                    f"Layer '{label}' not found.\n"
                    f"  Create a layer named exactly '{label}' containing {spec['desc']}.\n"
                    f"  See the 'Layer setup' tab for details."
                )
                continue

            n = len(paths)
            if n < spec["min"]:
                errors.append(
                    f"Layer '{label}' has {n} path(s), expected {spec['min']}.\n"
                    f"  It needs {spec['desc']}.\n"
                    f"  Make sure the paths are directly inside the layer (not in sub-groups)."
                )
            elif n > spec["max"]:
                errors.append(
                    f"Layer '{label}' has {n} paths, expected {spec['max']}.\n"
                    f"  It needs {spec['desc']}.\n"
                    f"  Remove extra paths or move them to another layer."
                )
            else:
                layers[label] = paths

        if errors:
            inkex.errormsg("Mug Generator — layer validation failed:\n\n" + "\n\n".join(errors))
            return

        mug_body_paths = layers["mug body"]
        handle_rail_paths = layers["handle rails"]
        side_rail_paths = layers["side rails"]
        profile_paths = layers["handle profile"]

        # Convert to mm
        mug_outer_mm = svg_to_mm(mug_body_paths[0])
        mug_inner_mm = svg_to_mm(mug_body_paths[1])
        inner_rail_mm = svg_to_mm(handle_rail_paths[0])
        outer_rail_mm = svg_to_mm(handle_rail_paths[1])

        # Side rail: X = half-width in mm, Y in mm (normalized to [0,1] later)
        # Single rail is used for both left and right (symmetric handle).
        side_rail = [(to_mm(p[0] * scale, doc_units), to_mm(p[1] * scale, doc_units))
                     for p in side_rail_paths[0]]

        # Handle profile: raw 2D shape (no coordinate inversion)
        handle_profile = [(p[0], p[1]) for p in profile_paths[0]]

        # Build mug surface (outer profile — used for cylinder wrapping)
        mug_surface = MugSurface([[p[0], p[1]] for p in mug_outer_mm])

        def mug_true_radius_at_z(z):
            return mug_surface.radius_at_z(z)

        # Compute number of stations
        from lib.rail_sampler import _cumulative_chord_lengths, _build_midpoint_curve
        midpoints = _build_midpoint_curve(inner_rail_mm, outer_rail_mm)
        mid_cl = _cumulative_chord_lengths(midpoints)
        mid_total = mid_cl[-1]

        n_stations = compute_n(
            self.options.fn, self.options.fa, self.options.fs, mid_total
        )

        # Re-parse mug body and handle profile with bezier subdivision
        # matching the revolution / loft resolution, so the surface
        # texture is congruent in both directions.  Line segments are
        # unaffected — only curves are resampled.
        import math
        from lib.units import to_mm as _to_mm

        avg_radius = (sum(p[0] for p in mug_outer_mm) / len(mug_outer_mm)
                      - mug_surface.axis_x)
        circumference = 2.0 * math.pi * avg_radius
        n_rev = compute_n(self.options.fn, self.options.fa,
                          self.options.fs, circumference)
        body_seg_len = circumference / n_rev
        handle_seg_len = mid_total / n_stations

        mm_per_svg = _to_mm(scale, doc_units)
        svg_body_seg = body_seg_len / mm_per_svg
        svg_handle_seg = handle_seg_len / mm_per_svg

        mug_body_paths = get_layer_paths(svg, "mug body",
                                         max_seg_len=svg_body_seg)
        profile_paths = get_layer_paths(svg, "handle profile",
                                        max_seg_len=svg_handle_seg)
        mug_outer_mm = svg_to_mm(mug_body_paths[0])
        mug_inner_mm = svg_to_mm(mug_body_paths[1])
        handle_profile = [(p[0], p[1]) for p in profile_paths[0]]

        # Sample rails
        stations = sample_rails(inner_rail_mm, outer_rail_mm, n_stations)

        # Apply side rails (same rail for both sides — symmetric handle)
        stations = apply_side_rails(stations, side_rail, side_rail)

        # Generate handle cross-sections (endcap profiles wrap onto mug cylinder)
        handle_stations_3d = generate_handle_stations(
            handle_profile, stations,
            mug_axis_x=mug_surface.axis_x,
            mug_radius_at_z=mug_true_radius_at_z,
        )

        # Clay shrinkage compensation: enlarge the model so the fired
        # piece matches the drawn size.
        shrinkage_pct = self.options.clay_shrinkage
        clay_scale = 100.0 / (100.0 - shrinkage_pct) if shrinkage_pct > 0 else 1.0

        # Build mug profiles for OpenSCAD — raw polygon vertices in path
        # order (not z-sorted).  X = radius from the document origin (mug axis).
        # All mug geometry is scaled by the clay shrinkage factor.
        scad_outer_profile = [[p[0] * clay_scale, p[1] * clay_scale] for p in mug_outer_mm]
        scad_inner_profile = [[p[0] * clay_scale, p[1] * clay_scale] for p in mug_inner_mm]
        scaled_handle_stations = [
            [[pt[0] * clay_scale, pt[1] * clay_scale, pt[2] * clay_scale]
             for pt in poly]
            for poly in handle_stations_3d
        ]
        scaled_handle_path = [
            [s.centroid[0] * clay_scale, s.centroid[1] * clay_scale,
             s.centroid[2] * clay_scale]
            for s in stations
        ]

        # Extract maker's mark (optional layer)
        mark_raw = get_layer_mark_polygons(svg, "mark")
        mark_enabled = len(mark_raw) > 0
        mark_polygons = []
        if mark_enabled:
            # Convert to mm with Y flip (so mark reads correctly from below)
            mark_mm = []
            for poly in mark_raw:
                converted = [
                    (to_mm(p[0] * scale, doc_units),
                     -to_mm(p[1] * scale, doc_units))
                    for p in poly
                ]
                mark_mm.append(converted)
            # Centre on (0, 0) by subtracting bounding-box centroid
            all_x = [p[0] for poly in mark_mm for p in poly]
            all_y = [p[1] for poly in mark_mm for p in poly]
            cx = (min(all_x) + max(all_x)) / 2
            cy = (min(all_y) + max(all_y)) / 2
            mark_polygons = [
                [(p[0] - cx, p[1] - cy) for p in poly]
                for poly in mark_mm
            ]
            # Apply clay shrinkage scaling
            mark_polygons = [
                [(p[0] * clay_scale, p[1] * clay_scale) for p in poly]
                for poly in mark_polygons
            ]

        # Compute draft-offset polygons and hole flags for mark
        import math as _math
        mark_polygons_draft = []
        mark_polygon_is_hole = []
        if mark_enabled:
            draft_offset = (self.options.mark_depth
                            * _math.tan(_math.radians(self.options.mark_draft_angle)))
            mark_polygons_draft = [
                offset_polygon(poly, draft_offset) for poly in mark_polygons
            ]
            mark_polygon_is_hole = compute_polygon_holes(mark_polygons)

        # Detect foot concavity for mould type
        concavity = mug_surface.detect_foot_concavity()
        mould_params = {
            "plaster_thickness": self.options.plaster_thickness,
            "wall_thickness": self.options.wall_thickness,
            "natch_radius": self.options.natch_radius,
            "funnel_wall_angle": self.options.funnel_wall_angle,
            "funnel_wall": self.options.funnel_wall,
            "flange_width": self.options.flange_width,
            "breather_hole_dia": self.options.breather_hole_dia,
            "breather_hole_count": self.options.breather_hole_count,
        }
        if concavity:
            mould_params["mould_type"] = 3
            mould_params["foot_concavity_z"] = concavity[0] * clay_scale
            mould_params["foot_concavity_radius"] = concavity[1] * clay_scale
        else:
            mould_params["mould_type"] = 2

        # Build output data
        data = {
            "mug_outer_profile": scad_outer_profile,
            "mug_inner_profile": scad_inner_profile,
            "handle_stations": scaled_handle_stations,
            "handle_path": scaled_handle_path,
            "mark_polygons": mark_polygons if mark_enabled else None,
            "mark_polygons_draft": mark_polygons_draft if mark_enabled else None,
            "mark_polygon_is_hole": mark_polygon_is_hole if mark_enabled else None,
            "mug_params": {
                "fn": self.options.fn,
                "fa": self.options.fa,
                "fs": self.options.fs,
                "axis_x": mug_surface.axis_x * clay_scale,
                "clay_shrinkage_pct": shrinkage_pct,
                "mark_enabled": mark_enabled,
                "mark_depth": self.options.mark_depth,
                "mark_inset": self.options.mark_inset,
                "mark_draft_angle": self.options.mark_draft_angle,
                **mould_params,
            },
        }

        # Write output
        run_all_emitters(data, output_dir)

        # Compute funnel outline for preview (in mm, pre-clay-scaling)
        funnel_outline_mm = self._funnel_outline(mug_outer_mm, mug_inner_mm)

        # Preview
        if self.options.preview:
            mug_outer_svg = [(p[0] * scale, p[1] * scale) for p in mug_body_paths[0]]
            side_rail_svg = [(p[0] * scale, p[1] * scale) for p in side_rail_paths[0]]
            draw_preview(svg, mug_outer_svg, stations, handle_stations_3d,
                         side_rail_svg, vb_bottom,
                         funnel_outline_mm=funnel_outline_mm)


    @staticmethod
    def _interp_profile_r(profile, z):
        """Interpolate the maximum radius of a profile at a given Z."""
        results = []
        n = len(profile)
        for i in range(n):
            j = (i + 1) % n
            z0, z1 = profile[i][1], profile[j][1]
            if min(z0, z1) <= z <= max(z0, z1) and abs(z1 - z0) > 1e-9:
                t = (z - z0) / (z1 - z0)
                r = profile[i][0] + t * (profile[j][0] - profile[i][0])
                results.append(r)
        return max(results) if results else profile[0][0]

    def _funnel_outline(self, outer_mm, inner_mm):
        """Compute the funnel right-half silhouette as [(r, z), ...] in mm.

        Returns the outer boundary of the funnel cross-section (right half
        only — the preview function mirrors it).  The lip-form region traces
        the inner profile boundary (clipped to neck_r) so the mug wall
        (outer minus inner) is excluded.
        """
        import math

        inner_top_z = max(p[1] for p in inner_mm)
        lip_top_z = max(p[1] for p in outer_mm)
        pour_hole_r = self._interp_profile_r(inner_mm, inner_top_z)

        fw = self.options.funnel_wall
        fla_w = self.options.flange_width
        cone_h = 50
        clearance = 0.5

        neck_r = pour_hole_r - clearance
        flange_z = inner_top_z
        cone_base_z = flange_z + fw
        cone_top_r = pour_hole_r + cone_h * math.tan(
            math.radians(self.options.funnel_wall_angle))
        flange_outer_r = pour_hole_r + fla_w

        # Compute lip_bottom_z: walk the inner profile downward from
        # lip_top_z.  The rim narrows; at some point the bowl widens.
        # Stop at the last narrowing node (just before the first widening).
        pts_desc = sorted(
            [(r, z) for r, z in inner_mm if z < lip_top_z - 0.01],
            key=lambda p: -p[1],
        )
        lip_bottom_z = lip_top_z - 3  # fallback
        for i in range(len(pts_desc) - 1):
            if pts_desc[i + 1][0] > pts_desc[i][0] + 0.01:  # widening
                lip_bottom_z = max(lip_top_z - 3, pts_desc[i][1])
                break

        # Trace the inner profile boundary in the lip region, clipped to
        # neck_r.  This excludes the mug wall (outer minus inner) from the
        # funnel preview.
        n_lip = 20
        dz = (lip_top_z - lip_bottom_z) / n_lip if n_lip > 0 else 0
        lip_right = []
        for i in range(n_lip + 1):
            z = lip_bottom_z + i * dz
            r = min(self._interp_profile_r(inner_mm, z), neck_r)
            lip_right.append((r, z))

        # Right-half outer boundary, bottom to top
        outline = [(0, lip_bottom_z)]
        outline.extend(lip_right)
        # If inner profile at lip_top_z is narrower than the neck, add a
        # corner at neck_r before continuing upward.
        if lip_right[-1][0] < neck_r - 0.01:
            outline.append((neck_r, lip_top_z))
        outline.extend([
            (neck_r, flange_z),
            (flange_outer_r, flange_z),
            (flange_outer_r, cone_base_z),
            (pour_hole_r, cone_base_z),
            (cone_top_r, cone_base_z + cone_h),
        ])
        return outline


if __name__ == "__main__":
    MugGeneratorEffect().run()
