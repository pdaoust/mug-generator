// Mug Generator — OpenSCAD assembly
// Requires BOSL2: https://github.com/BelfrySCAD/BOSL2
//
// This file is static and copied to the output directory by the extension.
// The generated data files are included at runtime.

include <BOSL2/std.scad>
include <BOSL2/skin.scad>

include <mug_params.scad>
include <mug_body_profile.scad>
include <handle_stations.scad>
include <mark_polygon.scad>

// Profiling gate — override with -D '_profile_module="name"' on the CLI.
_profile_module = is_undef(_profile_module) ? "" : _profile_module;

// --- Mug body (single closed cross-section, revolved) ---
//
// The profile is a closed polygon in the XZ half-plane (X = radius,
// Z = height), tracing outer wall → foot → floor → inner wall → rim.
// OpenSCAD's polygon() automatically closes last→first, and
// rotate_extrude() sweeps around the Z axis.

module mug_body() {
    rotate_extrude()
        polygon(points = mug_body_profile);
}

// --- Handle (lofted skin with endcaps) ---
// Extra stations at each end are snapped to the mug surface so the
// handle plugs cleanly into the body for the boolean union.
// caps=true lets BOSL2 triangulate and close the ends internally,
// ensuring proper vertex sharing between skin walls and endcaps.

// Outer profile = points 0..body_foot_idx (for radius interpolation)
_outer = [for (i = [0:body_foot_idx]) mug_body_profile[i]];

// Interpolate mug outer radius at height z from the outer profile.
function mug_r_at_z(z) =
    let(
        prof = _outer, n = len(prof),
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

mug_min_z = min([for (p = _outer) p[1]]);

// Z of the mug base centre (foot center on the axis).
_foot_center_z = mug_body_profile[body_foot_idx][1];

// Foot-roof points within 0.1mm of the foot roof.
// Bezier interpolation can round the inner foot-ring corner, making the
// roof slightly non-flat.  For debossed marks we use the lowest
// point so the stamp reaches the full surface; for embossed marks
// we use the highest so the stamp sits above the full surface.
_mark_tol = 0.1;
_foot_roof_z = [for (i = [0:body_foot_idx])
    let(z = mug_body_profile[i][1])
    if (abs(z - _foot_center_z) <= _mark_tol) z];
_mark_z = mark_inset
    ? min(_foot_roof_z)
    : max(_foot_roof_z);

_mark_draft = mark_depth * tan(mark_draft_angle);
_mark_slices = mark_draft_angle > 0
    ? max(2, round(mark_depth / mark_layer_height))
    : 1;

module mark_stamp() {
    // $fn = 0 so mark_fa / mark_fs control arc resolution here,
    // even when a global $fn is set for the rest of the mug.
    if (len(mark_points) > 0) {
        if (mark_draft_angle > 0) {
            _dz = mark_depth / _mark_slices;
            for (i = [0:_mark_slices - 1]) {
                // Debossed: 0 → -draft (inset deepens with z).
                // Embossed: +draft → 0 (outset at z=0, original at
                // z=mark_depth; mirror in assembly flips so the
                // widest end becomes the visible tip).
                _t = i / (_mark_slices - 1);
                _r = mark_inset
                    ? -_mark_draft * _t
                    :  _mark_draft * (1 - _t);
                translate([0, 0, i * _dz])
                    linear_extrude(height = _dz + 0.001)
                        offset(r = _r, $fn = 0, $fa = mark_fa, $fs = mark_fs)
                            polygon(points = mark_points, paths = mark_paths);
            }
        } else
            linear_extrude(height = mark_depth)
                polygon(points = mark_points, paths = mark_paths);
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

// --- Profiling dispatch ---
if (_profile_module == "") {
    mug_assembly();
} else if (_profile_module == "noop") {
    // Render nothing — measures pure startup cost.
} else if (_profile_module == "mug_body") {
    mug_body();
} else if (_profile_module == "handle") {
    handle();
} else if (_profile_module == "mark_stamp") {
    mark_stamp();
} else if (_profile_module == "mug_assembly") {
    mug_assembly();
}

// =====================================================================
// MUG VOLUME ESTIMATION
// =====================================================================

if (_profile_module == "") {
    _inner = [for (i = [body_foot_idx:len(mug_body_profile)-1])
        mug_body_profile[i]];
    _vnf_inner = rotate_sweep(_inner, caps=true, $fn=36);
    _v_mug_ml = round(abs(vnf_volume(_vnf_inner)) / 1000);

    echo(str(""));
    echo(str("=== MUG VOLUME ==="));
    echo(str("  Capacity:  ", _v_mug_ml, " mL"));
    echo(str("=================="));
}
