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

// Z of the mug base centre (where the profile meets the Z axis
// at the bottom — above mug_min_z for mugs with a foot ring).
_mark_z = mug_outer_profile[0][1];

_mark_draft = mark_depth * tan(mark_draft_angle);
_mark_half_draft = _mark_draft / 2;
_mark_slices = mark_draft_angle > 0
    ? max(2, round(mark_depth / mark_layer_height))
    : 1;

module mark_stamp() {
    if (len(mark_points) > 0) {
        _dz = mark_depth / _mark_slices;
        for (i = [0:_mark_slices - 1]) {
            _r = _mark_half_draft * (1 - 2 * (i + 0.5) / _mark_slices);
            translate([0, 0, i * _dz])
                linear_extrude(height = _dz + 0.001)
                    offset(r = _r)
                        polygon(points = mark_points, paths = mark_paths);
        }
    }
}

// --- Assembly ---

module mug_assembly() {
    union() {
        if (mark_enabled && mark_inset) {
            difference() {
                mug_body();
                translate([0, 0, _mark_z - 0.01])
                    render() mark_stamp();
            }
        } else if (mark_enabled && !mark_inset) {
            union() {
                mug_body();
                translate([0, 0, _mark_z + 0.01])
                    mirror([0, 0, 1])
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
