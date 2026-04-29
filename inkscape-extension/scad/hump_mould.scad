// Hump Mould Case — OpenSCAD
// Requires BOSL2: https://github.com/BelfrySCAD/BOSL2
//
// Generates a cylindrical case mould whose negative space is the
// mug's inner cavity (as if you filled the mug to the brim with
// plaster).  Pour plaster in, remove the case, flip — you have a
// hump mould for draping slabs.

include <BOSL2/std.scad>
include <lib/handle_geom.scad>

include <mug_params.scad>
include <mug_body_profile.scad>

// =====================================================================
// CLAY SHRINKAGE SCALING
// =====================================================================

_cs = clay_shrinkage_pct > 0 ? 100 / (100 - clay_shrinkage_pct) : 1;

_body = mug_body_polyline(mug_body_profile_bez, _cs);
_foot_idx = mug_foot_idx(_body, mug_body_profile_bez, _cs);

// =====================================================================
// INNER PROFILE (closed)
// =====================================================================
// Inner profile = body[body_foot_idx .. end], tracing from the foot
// center (r ≈ 0) up the inner wall to the inner rim.
// Add a closing point at (0, rim_z) so the polygon closes along the
// axis rather than cutting diagonally from inner rim to foot center.

_inner_raw = [for (i = [_foot_idx:len(_body)-1]) _body[i]];
_inner_rim_z = _inner_raw[len(_inner_raw)-1][1];
_inner = concat(_inner_raw, [[0, _inner_rim_z]]);

_inner_max_r = max([for (p = _inner) p[0]]);
_inner_min_z = min([for (p = _inner) p[1]]);
_inner_max_z = max([for (p = _inner) p[1]]);
_inner_z_range = _inner_max_z - _inner_min_z;

// =====================================================================
// CASE BLOCK
// =====================================================================
// Solid cylinder at z=0.  Height = inner profile height + wall_thickness
// (wall_thickness provides a solid floor at the bottom).
// The inner cavity is positioned inside so its foot sits at
// z = wall_thickness, with a small epsilon overlap for clean boolean.

_block_r = _inner_max_r + wall_thickness;
_block_h = _inner_z_range + wall_thickness;
_eps = 0.01;

module hump_mould_case() {
    difference() {
        cylinder(r = _block_r, h = _block_h);

        // Inner cavity translated so min_z aligns with wall_thickness,
        // nudged down by epsilon to punch through the top cleanly.
        translate([0, 0, wall_thickness - _inner_min_z + _eps])
            rotate_extrude(convexity = 4)
                polygon(points = _inner);
    }
}

// =====================================================================
// RENDER
// =====================================================================
// Foot at bottom, rim/opening at top — ready for pouring plaster.

hump_mould_case();
