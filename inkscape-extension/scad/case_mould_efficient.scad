// Case Mould Generator (plaster-efficient, peelable) — OpenSCAD
// Requires BOSL2: https://github.com/BelfrySCAD/BOSL2
//
// Thin-walled printed case mould: the mug is wrapped in a plaster
// chamber of thickness ``plaster_thickness`` which is enclosed in a
// printed shell of thickness ``wall_thickness``.  The shell is split
// at the A/B seam (Y = 0), and optionally at a horizontal Z-seam
// just below the foot inflection when the mug has a foot concavity
// or an inset maker's mark (both of which need a separate base part).

include <BOSL2/std.scad>
include <BOSL2/skin.scad>

include <mug_params.scad>
include <mug_body_profile.scad>
include <handle_stations_mould.scad>
include <mark_polygon.scad>

epsilon = 0.01;

// Greenware compensation — the mug geometry is stored at fired size
// and scaled up so that firing shrinkage lands on the drawn size.
// Mould construction parameters (wall_thickness, plaster_thickness,
// natch_radius) are NOT scaled.
_cs = clay_shrinkage_pct > 0 ? 100 / (100 - clay_shrinkage_pct) : 1;

// =====================================================================
// CLOSED HALF-PROFILE
// =====================================================================
// Walks mug_body_profile from the lip (index 0) down to the foot
// inflection point (body_foot_inflection_idx), scales every coordinate
// by _cs, then closes the polygon with three axis-adjacent legs so
// offset() treats it as a closed region.  Any foot concavity below
// body_foot_inflection_idx is discarded — it lives in the base part
// instead.

function scaled_closed_profile() =
    let(
        raw = [for (i = [0:body_foot_inflection_idx])
                 [mug_body_profile[i][0] * _cs,
                  mug_body_profile[i][1] * _cs]],
        // raw runs from (lip_r, z_lip) down to (foot_r, z_min).
        // Append axis closure: foot→axis, axis vertical, axis→lip.
        closed = concat(
            raw,
            [[0, z_min_scaled],
             [0, z_lip_scaled]]
        )
    ) closed;

// BOSL2 offset() on a closed polygon handles self-intersection and
// miter cases for us.  Large outsets (plaster_thickness + wall_thickness
// ≈ 31 mm) will warn in preview if a profile is too aggressively
// curved — that's a drawing problem, not a bug here.
//
// Outsetting a closed polygon pushes the axis-closure leg into
// negative X, which rotate_extrude() refuses.  Clamp to X ≥ 0 on the
// way out — the clamp only touches the axis leg, which is concealed
// by the revolution anyway.
function clamp_to_axis(pts) =
    [for (p = pts) [max(0, p[0]), p[1]]];

function offset_profile(d) =
    clamp_to_axis(
        d == 0 ? scaled_closed_profile()
               : offset(scaled_closed_profile(), r = d, closed = true)
    );

module revolve(d) {
    rotate_extrude(angle = 360, convexity = 4)
        polygon(offset_profile(d));
}

// =====================================================================
// FILLER TUBE
// =====================================================================
// A frustum sitting atop the body positive at z_lip, centred on the
// revolve axis.  Two halves: the outer frustum unions with the body
// positive, the inner frustum unions with the body inner wall and
// sinks ``wall_thickness + epsilon`` below z_lip so no roof forms
// over the mug cavity when the inner-wall solid is differenced out.

module filler_tube_outer() {
    r_bot = lip_r_scaled;
    r_top = r_bot + filler_tube_height * tan(filler_tube_angle);
    translate([0, 0, z_lip_scaled])
        cyl(h = filler_tube_height + epsilon,
            r1 = r_bot, r2 = r_top,
            anchor = BOTTOM);
}

module filler_tube_inner() {
    r_bot = lip_r_scaled - wall_thickness;
    h = filler_tube_height + wall_thickness + 2 * epsilon;
    r_top = r_bot + h * tan(filler_tube_angle);
    translate([0, 0, z_lip_scaled - wall_thickness - epsilon])
        cyl(h = h, r1 = r_bot, r2 = r_top, anchor = BOTTOM);
}

// =====================================================================
// HANDLE SWEEP
// =====================================================================
module handle_sweep(station_array) {
    if (handle_enabled && len(station_array) > 0)
        skin(station_array, slices = 0, caps = true);
}

// =====================================================================
// FOUR COMPOSITE SOLIDS
// =====================================================================
module mug_positive_solid() {
    union() {
        revolve(0);
        filler_tube_outer();
        handle_sweep(handle_stations_body_positive);
    }
}

module mug_inner_wall_solid() {
    union() {
        revolve(-wall_thickness);
        filler_tube_inner();
        handle_sweep(handle_stations_body_inner_wall);
    }
}

module shell_solid_geom() {
    union() {
        revolve(plaster_thickness);
        handle_sweep(handle_stations_shell_solid);
    }
}

module shell_outer_wall_solid() {
    union() {
        revolve(plaster_thickness + wall_thickness);
        handle_sweep(handle_stations_shell_outer_wall);
    }
}

// =====================================================================
// HALF-SPACE HELPERS
// =====================================================================
// Large cubes used to slice the composite solids at the A/B seam
// (Y = 0 plane) and, when ``needs_base`` is true, at the Z seam
// (z = z_min_scaled plane).

big = 2000;

module half_space_y_pos(y_cut) {
    translate([-big / 2, y_cut, -big / 2])
        cube([big, big, big]);
}

module half_space_z_pos(z_cut) {
    translate([-big / 2, -big / 2, z_cut])
        cube([big, big, big]);
}

// =====================================================================
// A/B RAW PART
// =====================================================================
// ab_raw() is the A-side half-shell with no registration features.
// Outer_half (shell_outer_wall_solid minus mug_inner_wall_solid)
// extends ``wall_thickness`` past the seam planes (Y ≥ −wall_thickness,
// and below z_min_scaled by wall_thickness when needs_base).  Inner_half
// (shell_solid_geom minus mug_positive_solid) is flush at Y=0 and
// z_min_scaled.  Subtracting one from the other leaves a wall of
// thickness ``wall_thickness`` along the seam planes — an annular wall
// at the A/B seam (no wall inside the mug cavity, so slip can flow)
// and, when needs_base, a floor at the Z seam.

module ab_raw() {
    difference() {
        // outer_half: shell skin + extended seam/floor
        intersection() {
            difference() {
                shell_outer_wall_solid();
                mug_inner_wall_solid();
            }
            half_space_y_pos(-wall_thickness);
            if (needs_base) half_space_z_pos(z_min_scaled - wall_thickness);
        }
        // inner_half: plaster cavity, flush at seam / z_min
        intersection() {
            difference() {
                shell_solid_geom();
                mug_positive_solid();
            }
            half_space_y_pos(0);
            if (needs_base) half_space_z_pos(z_min_scaled);
        }
    }
}

module a_part_raw() { ab_raw(); }
module b_part_raw() { mirror([0, 1, 0]) ab_raw(); }

// =====================================================================
// TOP-LEVEL — Phase 5 verification render
// =====================================================================
// Uncomment one at a time to inspect.
a_part_raw();
// b_part_raw();
// mug_positive_solid();
// mug_inner_wall_solid();
// shell_solid_geom();
// shell_outer_wall_solid();
