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

from lib.svg_layers import get_layer_paths, get_layer_mark_polygons
from lib.units import to_mm, parse_doc_units, parse_viewbox_bottom, parse_viewbox_scale
from lib.mug_surface import MugSurface
from lib.openscad_params import compute_n
from lib.rail_sampler import sample_rails
from lib.side_rail_extender import apply_side_rails
from lib.profile_transformer import generate_handle_stations, normalize_profile
from lib.scad_writer import run_all_emitters
from lib.preview import draw_preview
from lib.handle_nudge import nudge_handle_stations
from lib.profile_split import split_body_profile


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

        # Required layers
        required = {
            "mug body": {
                "min": 1, "max": 1,
                "desc": "one closed cross-section path (outer wall, rim, inner wall, floor)",
            },
        }

        for label, spec in required.items():
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

        # Optional handle layers — all three must be present to generate a handle
        handle_layers = {
            "handle rails": {
                "min": 2, "max": 2,
                "desc": "inner rail (near mug) and outer rail (far from mug)",
            },
            "handle side rails": {
                "min": 1, "max": 1,
                "desc": "one side rail path (X = half-width, Y = position along handle)",
            },
            "handle profile": {
                "min": 1, "max": 1,
                "desc": "one closed path for the handle cross-section shape",
            },
        }

        handle_enabled = True
        handle_errors = []
        for label, spec in handle_layers.items():
            try:
                paths = get_layer_paths(svg, label)
            except ValueError:
                handle_enabled = False
                continue

            n = len(paths)
            if n < spec["min"] or n > spec["max"]:
                handle_errors.append(
                    f"Layer '{label}' has {n} path(s), expected {spec['min']}.\n"
                    f"  It needs {spec['desc']}."
                )
                handle_enabled = False
            else:
                layers[label] = paths

        # If some handle layers exist but have errors, report them
        if handle_errors and any(l in layers for l in handle_layers):
            inkex.errormsg(
                "Mug Generator — handle layer validation failed:\n\n"
                + "\n\n".join(handle_errors)
            )
            return

        # All three handle layers must be present
        if handle_enabled:
            handle_enabled = all(l in layers for l in handle_layers)

        mug_body_paths = layers["mug body"]

        # Convert to mm — split closed profile at rim
        body_mm = svg_to_mm(mug_body_paths[0])
        body_profile, foot_idx = split_body_profile(body_mm)
        mug_outer_mm = body_profile[:foot_idx + 1]

        # Build mug surface (outer profile — used for cylinder wrapping)
        mug_surface = MugSurface([[p[0], p[1]] for p in mug_outer_mm])

        # Handle pipeline (only if all three handle layers are present)
        handle_stations_3d = []
        stations = []
        if handle_enabled:
            handle_rail_paths = layers["handle rails"]
            side_rail_paths = layers["handle side rails"]
            profile_paths = layers["handle profile"]

            inner_rail_mm = svg_to_mm(handle_rail_paths[0])
            outer_rail_mm = svg_to_mm(handle_rail_paths[1])

            side_rail = [(to_mm(p[0] * scale, doc_units), to_mm(p[1] * scale, doc_units))
                         for p in side_rail_paths[0]]

            handle_profile = [(p[0], p[1]) for p in profile_paths[0]]

            def mug_true_radius_at_z(z):
                return mug_surface.radius_at_z(z)

            from lib.rail_sampler import _cumulative_chord_lengths, _build_midpoint_curve
            midpoints = _build_midpoint_curve(inner_rail_mm, outer_rail_mm)
            mid_cl = _cumulative_chord_lengths(midpoints)
            mid_total = mid_cl[-1]

            n_stations = compute_n(
                self.options.fn, self.options.fa, self.options.fs, mid_total
            )

            # Re-parse with bezier subdivision matching OpenSCAD resolution
            from lib.units import to_mm as _to_mm

            mm_per_svg = _to_mm(scale, doc_units)
            if self.options.fn > 0:
                svg_fa = 360.0 / self.options.fn
                svg_fs = None
            else:
                svg_fa = self.options.fa
                svg_fs = self.options.fs / mm_per_svg if mm_per_svg > 0 else None

            mug_body_paths = get_layer_paths(svg, "mug body",
                                             fa_deg=svg_fa, fs=svg_fs)
            profile_paths = get_layer_paths(svg, "handle profile",
                                            fa_deg=svg_fa, fs=svg_fs)
            body_mm = svg_to_mm(mug_body_paths[0])
            body_profile, foot_idx = split_body_profile(body_mm)
            mug_outer_mm = body_profile[:foot_idx + 1]
            handle_profile = [(p[0], p[1]) for p in profile_paths[0]]

            stations = sample_rails(inner_rail_mm, outer_rail_mm, n_stations)
            stations = apply_side_rails(stations, side_rail, side_rail)

            handle_stations_3d = generate_handle_stations(
                handle_profile, stations,
                mug_axis_x=mug_surface.axis_x,
                mug_radius_at_z=mug_true_radius_at_z,
            )

        else:
            # Re-parse mug body with bezier subdivision even without handle
            from lib.units import to_mm as _to_mm

            mm_per_svg = _to_mm(scale, doc_units)
            if self.options.fn > 0:
                svg_fa = 360.0 / self.options.fn
                svg_fs = None
            else:
                svg_fa = self.options.fa
                svg_fs = self.options.fs / mm_per_svg if mm_per_svg > 0 else None

            mug_body_paths = get_layer_paths(svg, "mug body",
                                             fa_deg=svg_fa, fs=svg_fs)
            body_mm = svg_to_mm(mug_body_paths[0])
            body_profile, foot_idx = split_body_profile(body_mm)
            mug_outer_mm = body_profile[:foot_idx + 1]

        shrinkage_pct = self.options.clay_shrinkage

        # Build mug body profile for OpenSCAD — the full closed cross-section,
        # reordered to start at the rim split point with outer side first.
        # Data is emitted at actual (fired) size; clay shrinkage scaling
        # is applied in the mould/funnel SCAD files.
        scad_body_profile = [[p[0], p[1]] for p in body_profile]
        if handle_enabled:
            handle_stations_out = [
                [[pt[0], pt[1], pt[2]] for pt in poly]
                for poly in handle_stations_3d
            ]
            norm_profile = normalize_profile(handle_profile)
            scad_outer_profile = scad_body_profile[:foot_idx + 1]
            handle_stations_out = nudge_handle_stations(
                handle_stations_out, scad_outer_profile,
                axis_x=mug_surface.axis_x,
                station_frames=stations,
                norm_profile=norm_profile,
            )
            handle_path_out = [
                [s.centroid[0], s.centroid[1], s.centroid[2]]
                for s in stations
            ]
        else:
            handle_stations_out = []
            handle_path_out = []

        # Extract maker's mark (optional layer)
        mm_per_svg = to_mm(scale, doc_units)
        mark_svg_fs = self.options.mark_fs / mm_per_svg if mm_per_svg > 0 else None
        mark_raw = get_layer_mark_polygons(svg, "mark",
                                           fa_deg=self.options.mark_fa,
                                           fs=mark_svg_fs)
        mark_enabled = len(mark_raw) > 0
        mark_polygons = []
        if mark_enabled:
            # Convert to mm.  Negate X so the mark reads correctly
            # when viewed from below (flipping the mug swaps left/right).
            # Negate Y to convert from SVG (Y-down) to OpenSCAD (Y-up).
            mark_mm = []
            for poly in mark_raw:
                converted = [
                    (-to_mm(p[0] * scale, doc_units),
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

        # Detect foot concavity for mould type
        concavity = mug_surface.detect_foot_concavity()
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
        # A maker's mark requires a 3-part mould (mark is in the base)
        # even when the foot has no concavity.
        if concavity or mark_enabled:
            mould_params["mould_type"] = 3
            if concavity:
                mould_params["foot_concavity_z"] = concavity[0]
                mould_params["foot_concavity_radius"] = concavity[1]
        else:
            mould_params["mould_type"] = 2

        # Selective export flags.  Each subsidiary rib is demoted to False
        # when its parent mould is unchecked, since the rib file includes
        # parameters that only exist alongside the mould.
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

        # Build output data
        data = {
            "exports": exports,
            "mug_body_profile": scad_body_profile,
            "handle_stations": handle_stations_out,
            "handle_path": handle_path_out,
            "mark_polygons": mark_polygons if mark_enabled else None,
            "mug_params": {
                "fn": self.options.fn,
                "fa": self.options.fa,
                "fs": self.options.fs,
                "axis_x": mug_surface.axis_x,
                "body_foot_idx": foot_idx,
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

        # Write output
        run_all_emitters(data, output_dir)

        # Compute funnel outline for preview (in mm, pre-clay-scaling)
        inner_mm = body_profile[foot_idx:]
        funnel_outline_mm = self._funnel_outline(mug_outer_mm, inner_mm)

        # Preview
        if self.options.preview:
            mug_outer_svg = [(p[0] * scale, p[1] * scale) for p in mug_body_paths[0]]
            side_rail_svg = None
            if handle_enabled:
                side_rail_paths = layers["handle side rails"]
                side_rail_svg = [(p[0] * scale, p[1] * scale) for p in side_rail_paths[0]]
            # Use nudged stations for preview so it shows the final geometry
            preview_stations = handle_stations_out if handle_enabled else handle_stations_3d
            draw_preview(svg, mug_outer_svg, stations, preview_stations,
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
