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

// --- Handle (lofted skin) ---

module handle() {
    skin(handle_stations, slices=0, caps=false, method="reindex");
}

// --- Assembly ---

union() {
    mug_body();
    handle();
}
