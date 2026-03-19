// Mug Generator — OpenSCAD assembly
// Requires BOSL2: https://github.com/BelfrySCAD/BOSL2
//
// This file is static and copied to the output directory by the extension.
// The generated data files are included at runtime.

include <BOSL2/std.scad>
include <BOSL2/skin.scad>

include <mug_params.scad>
include <mug_outer_profile.scad>
include <mug_inner_profile.scad>
include <handle_stations.scad>
include <mark_polygon.scad>

// --- Mug body (outer minus inner, both drawn profiles) ---
//
// The profiles are closed polygons in the XZ half-plane (X = radius,
// Z = height), passed in vertex order from the SVG paths.  OpenSCAD's
// polygon() automatically closes last→first, and rotate_extrude()
// sweeps around the Z axis.

module mug_outer() {
    rotate_extrude()
        polygon(points = mug_outer_profile);
}

module mug_inner() {
    rotate_extrude()
        polygon(points = mug_inner_profile);
}

module mug_body() {
    difference() {
        mug_outer();
        mug_inner();
    }
}

// --- Handle (lofted skin with endcaps) ---
// Extra sunken stations at each end push 1 mm radially inward so the
// handle plugs into the mug wall for a clean boolean overlap.
// caps=true lets BOSL2 triangulate and close the ends internally,
// ensuring proper vertex sharing between skin walls and endcaps.

function nudge_radial(pts, axis_x, amount) =
    [for(p = pts)
        let(
            dx = p[0] - axis_x,
            dy = p[1],
            r = norm([dx, dy]),
            scale = r > 0.001 ? (r + amount) / r : 1
        )
        [axis_x + dx * scale, dy * scale, p[2]]
    ];

handle_stations_extended = handle_enabled ? concat(
    [nudge_radial(handle_stations[0], mug_axis_x, -1)],
    handle_stations,
    [nudge_radial(handle_stations[len(handle_stations)-1], mug_axis_x, -1)]
) : [];

module handle() {
    if (handle_enabled)
        skin(handle_stations_extended, slices=0, caps=true, method="reindex");
}

// --- Maker's mark ---

mug_min_z = min([for (p = mug_outer_profile) p[1]]);

_mark_eps = 0.001;

module _mark_skin(i, z_lo, z_hi) {
    skin([
        [for (p = mark_polygons[i]) [p[0], p[1], z_lo]],
        [for (p = mark_polygons_draft[i]) [p[0], p[1], z_hi]]
    ], slices = 0, caps = true, method = "direct");
}

module mark_stamp() {
    if (len(mark_polygons) > 0)
        difference() {
            for (i = [0:len(mark_polygons) - 1])
                if (!mark_polygon_is_hole[i])
                    _mark_skin(i, 0, mark_depth);
            for (i = [0:len(mark_polygons) - 1])
                if (mark_polygon_is_hole[i])
                    _mark_skin(i, -_mark_eps, mark_depth + _mark_eps);
        }
}

// --- Assembly ---

module mug_assembly() {
    union() {
        if (mark_enabled && mark_inset) {
            difference() {
                mug_body();
                translate([0, 0, mug_min_z])
                    mark_stamp();
            }
        } else if (mark_enabled && !mark_inset) {
            union() {
                mug_body();
                translate([0, 0, mug_min_z - mark_depth])
                    mark_stamp();
            }
        } else {
            mug_body();
        }
        if (handle_enabled)
            handle();
    }
}

mug_assembly();
