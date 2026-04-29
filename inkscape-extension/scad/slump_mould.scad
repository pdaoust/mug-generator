// Slump Mould Case — OpenSCAD
// Requires BOSL2: https://github.com/BelfrySCAD/BOSL2
//
// Generates a hollow cylindrical case with the outer body profile
// rising upside-down from the floor.  Pour plaster around the
// positive to create a slump mould (concave plaster form for
// pressing slabs into).
//
// The maker's mark (if enabled) is applied to the foot of the
// positive so it transfers through: positive → plaster → clay.

include <BOSL2/std.scad>
include <lib/handle_geom.scad>

include <mug_params.scad>
include <mug_body_profile.scad>
include <mark_polygon.scad>

// =====================================================================
// CLAY SHRINKAGE SCALING
// =====================================================================

_cs = clay_shrinkage_pct > 0 ? 100 / (100 - clay_shrinkage_pct) : 1;

_body = mug_body_polyline(mug_body_profile_bez, _cs);
_foot_idx = mug_foot_idx(_body, mug_body_profile_bez, _cs);
_mark_data = mark_tessellate(mark_bezpaths, mark_fa, mark_fs, _cs);
_mpoints = _mark_data[0];
_mark_paths_idx = _mark_data[1];
_mark_depth_s = mark_depth * _cs;

// =====================================================================
// OUTER PROFILE (foot-first)
// =====================================================================
// _outer goes rim -> foot.  Reverse so it goes foot -> rim.

_outer_rim_first = [for (i = [0:_foot_idx]) _body[i]];
_outer = [for (i = [len(_outer_rim_first)-1:-1:0]) _outer_rim_first[i]];

_outer_max_x = max([for (p = _outer) p[0]]);
_outer_min_y = min([for (p = _outer) p[1]]);
_outer_max_y = max([for (p = _outer) p[1]]);

// Index of the point with maximum x
_max_x_idx = [for (i = [0:len(_outer)-1])
    if (_outer[i][0] == _outer_max_x) i][0];

// =====================================================================
// POSITIVE PROFILE
// =====================================================================
// foot_center -> around foot -> up wall -> max_x point ->
// vertical to (max_x, max_y) -> horizontal to (0, max_y) -> close.
// Preserves concave foot; cuts off any inward hook above max_x.

_profile = concat(
    [for (i = [0:_max_x_idx]) _outer[i]],   // foot -> max_x point
    [[_outer_max_x, _outer_max_y]],           // vertical to top
    [[0, _outer_max_y]]                       // horizontal to axis
);

// Profile bounds
_prof_max_x = max([for (p = _profile) p[0]]);
_prof_min_y = min([for (p = _profile) p[1]]);
_prof_max_y = max([for (p = _profile) p[1]]);
_prof_z_range = _prof_max_y - _prof_min_y;

// =====================================================================
// FLIP UPSIDE-DOWN
// =====================================================================
// Normalize so min_y=0, negate Y, shift back to positive.
// Result: rim at Y=0 (bottom), foot at Y=z_range (top).

_flipped = [for (p = _profile)
    [p[0], _prof_z_range - (p[1] - _prof_min_y)]
];

// =====================================================================
// MAKER'S MARK
// =====================================================================
// The foot center (after flipping) is at the top of the positive.
// The mark transfers: positive -> plaster mould -> clay piece.
// Debossed on mug = subtract from positive; embossed = add to positive.

_foot_center_z_orig = _body[_foot_idx][1];
_mark_tol = 0.1;
_foot_roof_z_vals = [for (i = [0:_foot_idx])
    let(z = _body[i][1])
    if (abs(z - _foot_center_z_orig) <= _mark_tol) z];
_mark_z_orig = mark_inset
    ? min(_foot_roof_z_vals)
    : max(_foot_roof_z_vals);

// After flipping: original z -> _prof_z_range - (z - _prof_min_y)
_mark_z_flipped = _prof_z_range - (_mark_z_orig - _prof_min_y);

_mark_draft_s = _mark_depth_s * tan(mark_draft_angle);
_mark_slices = mark_draft_angle > 0
    ? max(2, round(_mark_depth_s / mark_layer_height))
    : 1;

module mark_stamp() {
    if (len(_mpoints) > 0) {
        if (mark_draft_angle > 0) {
            _dz = _mark_depth_s / _mark_slices;
            for (i = [0:_mark_slices - 1]) {
                _t = i / (_mark_slices - 1);
                _r = mark_inset
                    ? -_mark_draft_s * _t
                    :  _mark_draft_s * (1 - _t);
                translate([0, 0, i * _dz])
                    linear_extrude(height = _dz + 0.001, convexity = 4)
                        offset(r = _r, $fn = 0, $fa = mark_fa, $fs = mark_fs)
                            polygon(points = _mpoints, paths = _mark_paths_idx);
            }
        } else
            linear_extrude(height = _mark_depth_s, convexity = 4)
                polygon(points = _mpoints, paths = _mark_paths_idx);
    }
}

// =====================================================================
// CYLINDER DIMENSIONS
// =====================================================================

_eps = 0.01;
_cyl_inner_r = _prof_max_x + plaster_thickness;
_cyl_outer_r = _cyl_inner_r + wall_thickness;
_cyl_h = wall_thickness + _prof_z_range + plaster_thickness;

// =====================================================================
// POSITIVE (with optional mark)
// =====================================================================

module _positive_raw() {
    rotate_extrude(convexity = 4)
        polygon(points = _flipped);
}

module positive() {
    // After flipping, the foot is at the TOP and the body extends
    // downward.  Inset (debossed on mug) must go DOWN into the
    // positive; embossed must protrude UP out of it.
    if (mark_enabled && mark_inset) {
        difference() {
            _positive_raw();
            // Stamp mirrored to extend downward into the positive.
            translate([0, 0, _mark_z_flipped + _eps])
                mirror([0, 0, 1])
                    render() mark_stamp();
        }
    } else if (mark_enabled && !mark_inset) {
        union() {
            _positive_raw();
            // Stamp extends upward out of the foot surface.
            translate([0, 0, _mark_z_flipped - _eps])
                mark_stamp();
        }
    } else {
        _positive_raw();
    }
}

// =====================================================================
// SLUMP MOULD CASE
// =====================================================================

module slump_mould_case() {
    union() {
        // Hollow cylinder (case walls + floor)
        difference() {
            cylinder(r = _cyl_outer_r, h = _cyl_h);
            translate([0, 0, wall_thickness])
                cylinder(r = _cyl_inner_r, h = _cyl_h);
        }

        // Upside-down positive rising from the floor.
        // Overlaps floor by epsilon for clean union.
        translate([0, 0, wall_thickness - _eps])
            positive();
    }
}

// =====================================================================
// RENDER
// =====================================================================

slump_mould_case();
