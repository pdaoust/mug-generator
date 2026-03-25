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
// Extra stations at each end are snapped to the mug surface so the
// handle plugs cleanly into the body for the boolean union.
// caps=true lets BOSL2 triangulate and close the ends internally,
// ensuring proper vertex sharing between skin walls and endcaps.

// Interpolate mug outer radius at height z from the profile polygon.
function mug_r_at_z(z) =
    let(
        prof = mug_outer_profile, n = len(prof),
        results = [for (i = [0:n-1])
            let(j = (i + 1) % n,
                z0 = prof[i][1], z1 = prof[j][1],
                zlo = min(z0, z1), zhi = max(z0, z1))
            if (zlo <= z && z <= zhi && abs(zhi - zlo) > 1e-9)
                let(t = (z - z0) / (z1 - z0))
                prof[i][0] + t * (prof[j][0] - prof[i][0])
        ]
    ) len(results) > 0 ? max(results) : prof[0][0];

// Centroid of a cross-section (list of 3D points).
function _centroid(pts) =
    let(n = len(pts))
    [for (j = [0:2]) let(s = [for (p = pts) p[j]]) s * [for (_ = s) 1] / n];

// Snap entire cross-section inside the mug surface (for end-caps).
// Translates the whole station uniformly based on centroid position.
function snap_to_mug(pts, axis_x, overshoot = 0.5) =
    let(
        c = _centroid(pts),
        dx = c[0] - axis_x,
        dy = c[1],
        r = norm([dx, dy]),
        mug_r = mug_r_at_z(c[2]),
        target_r = mug_r - overshoot,
        shift = r > 0.001 ? max(0, r - target_r) : 0,
        dir_x = r > 0.001 ? dx / r : 1,
        dir_y = r > 0.001 ? dy / r : 0
    )
    [for (p = pts)
        [p[0] - shift * dir_x, p[1] - shift * dir_y, p[2]]
    ];

// Handle stations arrive pre-nudged from Python.
// Extra end-cap stations are snapped inside the mug surface for a
// clean boolean union.
_n_hs = len(handle_stations);
handle_stations_extended = handle_enabled ? concat(
    [snap_to_mug(handle_stations[0], mug_axis_x)],
    handle_stations,
    [snap_to_mug(handle_stations[_n_hs-1], mug_axis_x)]
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
