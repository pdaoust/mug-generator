// Mug Generator — OpenSCAD assembly
// Requires BOSL2: https://github.com/BelfrySCAD/BOSL2
//
// This file is static and copied to the output directory by the extension.
// The generated data files are included at runtime.

include <BOSL2/std.scad>
include <BOSL2/skin.scad>
include <lib/handle_geom.scad>

include <mug_params.scad>
include <mug_body_profile.scad>
include <handle_bezpaths.scad>
include <mark_polygon.scad>

_body = mug_body_polyline(mug_body_profile_bez);
_foot_idx = mug_foot_idx(_body, mug_body_profile_bez);

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
        polygon(points = bez_to_polyline(mug_body_profile_bez,
                                         closed = mug_body_profile_closed));
}

// --- Handle (lofted skin with endcaps) ---
// Extra stations at each end are snapped to the mug surface so the
// handle plugs cleanly into the body for the boolean union.
// caps=true lets BOSL2 triangulate and close the ends internally,
// ensuring proper vertex sharing between skin walls and endcaps.

// Outer profile = body[0..foot] (for foot-roof Z search).
_outer = [for (i = [0:_foot_idx]) _body[i]];

// Mug outer radius at height z — analytic on the body bezpath.
// mug_r_at_z(bez, z) lives in handle_geom.scad and is resolution-
// independent (solves the per-segment cubic in u against y=z).
// The wrapper preserves the prior single-arg call shape used here.
function mug_r_at_z(z) =
    let(r = mug_r_at_z_bez(mug_body_profile_bez, z))
    is_undef(r) ? _outer[0][0] : r;

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
// Compute handle stations at SCAD render time from raw rail and
// profile bezpaths.
_handle_stations_scad = handle_enabled
    ? let(
        raw_stations = sample_rails_bez(
            handle_inner_rail_bez,
            handle_outer_rail_bez,
            handle_n_stations
        ),
        with_sides = apply_side_rails(
            raw_stations,
            handle_side_rail_polyline,
            handle_side_rail_polyline
        ),
        profile_polyline = bez_to_polyline(handle_profile_bez, closed=true),
        norm_profile = normalize_profile(profile_polyline),
        polys = generate_handle_stations_bez(
            profile_polyline, with_sides,
            axis_x = mug_axis_x,
            body_bez = mug_body_profile_bez
        ),
        nudged = nudge_handle_stations_bez(
            polys, with_sides, norm_profile,
            mug_body_profile_bez, mug_axis_x
        )
    ) nudged
    : [];

_n_hs = len(_handle_stations_scad);
handle_stations_extended = handle_enabled ? concat(
    [snap_to_mug(_handle_stations_scad[0], mug_axis_x)],
    _handle_stations_scad,
    [snap_to_mug(_handle_stations_scad[_n_hs-1], mug_axis_x)]
) : [];

module handle() {
    if (handle_enabled)
        skin(handle_stations_extended, slices=0, caps=true, method="reindex");
}

// --- Maker's mark ---

mug_min_z = min([for (p = _outer) p[1]]);

// Z of the mug base centre (foot center on the axis).
_foot_center_z = _body[_foot_idx][1];

// Foot-roof points within 0.1mm of the foot roof.
// Bezier interpolation can round the inner foot-ring corner, making the
// roof slightly non-flat.  For debossed marks we use the lowest
// point so the stamp reaches the full surface; for embossed marks
// we use the highest so the stamp sits above the full surface.
_mark_tol = 0.1;
_foot_roof_z = [for (i = [0:_foot_idx])
    let(z = _body[i][1])
    if (abs(z - _foot_center_z) <= _mark_tol) z];
_mark_z = mark_inset
    ? min(_foot_roof_z)
    : max(_foot_roof_z);

_mark_draft = mark_depth * tan(mark_draft_angle);
_mark_slices = mark_draft_angle > 0
    ? max(2, round(mark_depth / mark_layer_height))
    : 1;

_mark_data = mark_tessellate(mark_bezpaths, mark_fa, mark_fs);
_mark_pts = _mark_data[0];
_mark_paths_idx = _mark_data[1];

module mark_stamp() {
    // $fn = 0 so mark_fa / mark_fs control arc resolution here,
    // even when a global $fn is set for the rest of the mug.
    if (len(_mark_pts) > 0) {
        if (mark_draft_angle > 0) {
            _dz = mark_depth / _mark_slices;
            for (i = [0:_mark_slices - 1]) {
                _t = i / (_mark_slices - 1);
                _r = mark_inset
                    ? -_mark_draft * _t
                    :  _mark_draft * (1 - _t);
                translate([0, 0, i * _dz])
                    linear_extrude(height = _dz + 0.001)
                        offset(r = _r, $fn = 0, $fa = mark_fa, $fs = mark_fs)
                            polygon(points = _mark_pts, paths = _mark_paths_idx);
            }
        } else
            linear_extrude(height = mark_depth)
                polygon(points = _mark_pts, paths = _mark_paths_idx);
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
    _inner = [for (i = [_foot_idx:len(_body)-1]) _body[i]];
    _vnf_inner = rotate_sweep(_inner, caps=true, $fn=36);
    _v_mug_ml = round(abs(vnf_volume(_vnf_inner)) / 1000);

    echo(str(""));
    echo(str("=== MUG VOLUME ==="));
    echo(str("  Capacity:  ", _v_mug_ml, " mL"));
    echo(str("=================="));
}
