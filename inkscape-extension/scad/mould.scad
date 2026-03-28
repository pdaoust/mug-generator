// Case Mould Generator — OpenSCAD
// Requires BOSL2: https://github.com/BelfrySCAD/BOSL2
//
// Generates a 2- or 3-part plaster case mould for slip-casting.
// Each part is a bucket: floor = seam plane (solid mug positive
// protrudes from it), open top = opposite face (pour plaster here).
//
// The mug positive is printed solid — use lightning infill or
// similar in your slicer for a strong but light print.

include <BOSL2/std.scad>
include <BOSL2/skin.scad>

include <mug_params.scad>
include <mug_body_profile.scad>
include <handle_stations.scad>
include <mark_polygon.scad>

// --- Render control ---
render_part = "all";   // "all", "half_a", "half_b", "base"
explode_gap = 20;

// =====================================================================
// CLAY SHRINKAGE SCALING
// =====================================================================
// Data files contain actual (fired) dimensions.  The mould needs
// pre-shrinkage (greenware) dimensions so the fired piece comes out
// the right size.  Mould construction parameters (plaster_thickness,
// wall_thickness, natch_radius, etc.) are NOT scaled.

_cs = clay_shrinkage_pct > 0 ? 100 / (100 - clay_shrinkage_pct) : 1;

_body = [for (p = mug_body_profile) p * _cs];
_hstations = handle_enabled
    ? [for (s = handle_stations) [for (p = s) p * _cs]]
    : [];
_mpoints = [for (p = mark_points) p * _cs];
_axis = mug_axis_x * _cs;
_mark_depth = mark_depth * _cs;
_tube_h = filler_tube_height * _cs;

// =====================================================================
// DERIVED PROFILES
// =====================================================================

// Outer profile = body[0..body_foot_idx]
_outer = [for (i = [0:body_foot_idx]) _body[i]];

// Mould profile: outer wall + filler tube (inner points removed).
// body[0] = split point (rim), body[body_foot_idx] = foot center (r≈0).
// Tube: up from split point at same r, then inward to axis.
// Polygon auto-closes from (0, tube_top_z) back to split point.
_split_r = _body[0][0];
_split_z = _body[0][1];
_tube_top_z = _split_z + _tube_h;

_mould_profile = concat(
    [for (i = [0:body_foot_idx]) _body[i]],
    [[0, _tube_top_z],
     [_split_r, _tube_top_z]]
);

// =====================================================================
// DERIVED VALUES
// =====================================================================

mug_max_radius = max([for (p = _outer) p[0]]);
mug_max_z = max([for (p = _outer) p[1]]);
mug_min_z = min([for (p = _outer) p[1]]);

_use_keys = (alignment_type == "keys");
_key_tol_half = _use_keys ? key_tolerance / 2 : 0;
_key_r_bump   = natch_radius - _key_tol_half;
_key_r_socket = natch_radius + _key_tol_half;

inner_top_z = _tube_top_z;
handle_max_y = handle_enabled
    ? max([for (s = _hstations) for (p = s) abs(p[1])])
    : 0;
mould_y_half = max(mug_max_radius, handle_max_y) + plaster_thickness;

// =====================================================================
// MUG MODULES
// =====================================================================

// Mug body: just revolve the closed cross-section.
module mug_body() {
    rotate_extrude(convexity = 4) polygon(points = _body);
}

// --- Maker's mark stamp ---
_foot_center_z = _body[body_foot_idx][1];
_mark_tol = 0.25 * _mark_depth;
_foot_roof_z_mould = [for (i = [0:body_foot_idx])
    let(z = _body[i][1])
    if (abs(z - _foot_center_z) <= _mark_tol) z];
_mark_z = mark_inset
    ? min(_foot_roof_z_mould)
    : max(_foot_roof_z_mould);

_mark_draft = _mark_depth * tan(mark_draft_angle);
_mark_half_draft = _mark_draft / 2;
_mark_slices = mark_draft_angle > 0
    ? max(2, round(_mark_depth / mark_layer_height))
    : 1;

module mark_stamp() {
    if (len(_mpoints) > 0) {
        _dz = _mark_depth / _mark_slices;
        for (i = [0:_mark_slices - 1]) {
            _r = _mark_half_draft * (1 - 2 * (i + 0.5) / _mark_slices);
            translate([0, 0, i * _dz])
                linear_extrude(height = _dz + 0.001, convexity = 4)
                    offset(r = _r)
                        polygon(points = _mpoints, paths = mark_paths);
        }
    }
}

// Solid mould positive: revolve the mould profile (outer + tube, no inner).
module _mug_solid_raw() {
    rotate_extrude(convexity = 4) polygon(points = _mould_profile);
}

module mug_solid() {
    if (mark_enabled && mark_inset) {
        difference() {
            _mug_solid_raw();
            translate([0, 0, _mark_z - 0.01])
                render() mark_stamp();
        }
    } else if (mark_enabled && !mark_inset) {
        union() {
            _mug_solid_raw();
            translate([0, 0, _mark_z + 0.01])
                mirror([0, 0, 1])
                    mark_stamp();
        }
    } else {
        _mug_solid_raw();
    }
}

// Centroid of a cross-section (list of 3D points).
function _centroid(pts) =
    let(n = len(pts))
    [for (j = [0:2]) let(s = [for (p = pts) p[j]]) s * [for (_ = s) 1] / n];

// Snap entire cross-section inside the mug surface (for end-caps).
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

_n_hs = len(_hstations);
handle_stations_extended = handle_enabled ? concat(
    [snap_to_mug(_hstations[0], _axis)],
    _hstations,
    [snap_to_mug(_hstations[_n_hs-1], _axis)]
) : [];

module handle() {
    if (handle_enabled)
        skin(handle_stations_extended, slices=0, caps=true, method="reindex");
}

// Mug positive: solid + handle.
module mug_positive() {
    mug_solid();
    if (handle_enabled) handle();
}

// Centroid of outermost handle points (max X per station) —
// approximates the outer handle rail for natch placement.
_outer_handle_pts = handle_enabled ? [for (s = _hstations)
    let(xs = [for (p = s) p[0]],
        mx = max(xs),
        candidates = [for (p = s) if (abs(p[0] - mx) < 0.01) p])
    candidates[0]
] : [];
_n_ohp = len(_outer_handle_pts);
handle_outer_centroid = _n_ohp > 0
    ? [ sum([for (p = _outer_handle_pts) p[0]]) / _n_ohp,
        sum([for (p = _outer_handle_pts) p[1]]) / _n_ohp,
        sum([for (p = _outer_handle_pts) p[2]]) / _n_ohp ]
    : [mug_max_radius + 20, 0, (mug_max_z + mug_min_z) / 2];

// Interpolate mug radius at Z — works with unsorted profiles.
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

// Split Z for the 3-part mould.
_foot_z = (is_undef(foot_concavity_z)
        ? (mark_enabled ? _mark_z : 0)
        : foot_concavity_z * _cs)
    + (mark_enabled && mark_inset ? _mark_depth : 0);


// Handle rail projections onto the XZ plane (2D mould coordinates:
// X = 3D X, Y = 3D Z).
_handle_inner_2d = handle_enabled ? [for (s = _hstations)
    let(xs = [for (p = s) p[0]],
        mn = min(xs),
        pts = [for (p = s) if (abs(p[0] - mn) < 0.01) p])
    [pts[0][0], pts[0][2]]
] : [];

_handle_outer_2d = handle_enabled ? [for (s = _hstations)
    let(xs = [for (p = s) p[0]],
        mx = max(xs),
        pts = [for (p = s) if (abs(p[0] - mx) < 0.01) p])
    [pts[0][0], pts[0][2]]
] : [];

_handle_outline_2d = handle_enabled ? concat(
    _handle_outer_2d,
    [for (i = [len(_handle_inner_2d)-1:-1:0]) _handle_inner_2d[i]]
) : [];

// =====================================================================
// 2D MOULD PRIMITIVES (in XY plane where X = 3D X, Y = 3D Z height)
// =====================================================================

// Mould interior boundary: full plaster around the mug body, half
// plaster around the handle, gap between mug and handle filled solid.
// Clipped at inner_top_z (filler tube height).
module mould_hull_2d() {
    difference() {
        union() {
            // 1. Mould profile (outer + tube) with full plaster
            offset(r = plaster_thickness) {
                polygon(points = _mould_profile);
                mirror([1, 0]) polygon(points = _mould_profile);
            }

            if (handle_enabled) {
                // 2. Handle outline with half plaster
                offset(r = plaster_thickness / 2)
                    polygon(points = _handle_outline_2d);
            }

            // 3. Fill gap between mug and handle (no offset)
            polygon(points = _mould_profile);
            mirror([1, 0]) polygon(points = _mould_profile);
            if (handle_enabled)
                polygon(points = _handle_outer_2d);
        }
        // Clip everything above inner_top_z
        translate([-1000, inner_top_z])
            square([2000, 1000]);
    }
}

// Outer hull = mould hull + wall_thickness
module mould_outer_hull_2d() {
    offset(r = wall_thickness) mould_hull_2d();
}

// Wall ring = outer hull minus inner hull
module mould_wall_ring_2d() {
    difference() {
        mould_outer_hull_2d();
        mould_hull_2d();
    }
}

// =====================================================================
// 3D EXTRUSIONS (centered on Y=0, spanning full mould width)
// =====================================================================

_full_y = 2 * (mould_y_half + wall_thickness);

module full_walls() {
    rotate([90, 0, 0])
        linear_extrude(height = _full_y, center = true, convexity = 4)
            mould_wall_ring_2d();
}

module full_outer_hull() {
    rotate([90, 0, 0])
        linear_extrude(height = _full_y, center = true, convexity = 4)
            mould_outer_hull_2d();
}

// =====================================================================
// CLIPPING HELPERS
// =====================================================================

module clip_y_pos() { translate([0,  500, 0]) cube(1000, center = true); }
module clip_y_neg() { translate([0, -500, 0]) cube(1000, center = true); }
module clip_z_above(z) { translate([0, 0, z + 500]) cube(1000, center = true); }
module clip_z_below(z) { translate([0, 0, z - 500]) cube(1000, center = true); }

// =====================================================================
// SEAM FLOORS
// =====================================================================

_y_seam_thickness = 2 * wall_thickness;
_z_seam_thickness = wall_thickness;

module y_seam_floor(pos_y) {
    // Part B with keys needs a thicker floor so the hemisphere
    // sockets are fully enclosed.
    _ysf_thick = (_use_keys && !pos_y)
        ? 2 * (wall_thickness + _key_r_socket)
        : _y_seam_thickness;
    intersection() {
        rotate([90, 0, 0])
            linear_extrude(height = _ysf_thick, center = true, convexity = 4)
                mould_outer_hull_2d();
        if (pos_y) clip_y_neg(); else clip_y_pos();
    }
}

module z_seam_floor(z_split) {
    intersection() {
        full_outer_hull();
        translate([0, 0, z_split + _z_seam_thickness / 2])
            cube([2000, 2000, _z_seam_thickness], center = true);
    }
    // Backing shells so the base_keys_bumps() subtraction has
    // material to carve into on the upper-half sidewalls.
    if (_use_keys) {
        _bsr = _key_r_bump + wall_thickness;
        translate([0, base_natch_y, z_split + _z_seam_thickness + 0.01]) {
            rotate([180, 0, 0]) _hemisphere(_bsr);
            _teardrop_cone(_bsr, [90, 180, 0]);
        }
        translate([0, -base_natch_y, z_split + _z_seam_thickness + 0.01]) {
            rotate([180, 0, 0]) _hemisphere(_bsr);
            _teardrop_cone(_bsr, [-90, 180, 0]);
        }
    }
}

// =====================================================================
// TWO-PART MOULD HALVES
// =====================================================================

module case_half(pos_y) {
    union() {
        intersection() {
            full_walls();
            if (pos_y) clip_y_pos(); else clip_y_neg();
        }
        y_seam_floor(pos_y);

        intersection() {
            mug_positive();
            if (pos_y) clip_y_pos(); else clip_y_neg();
            full_outer_hull();
        }
    }
}

// --- Seam alignment (on the Y=0 plane) ---
_natch_mid_z = (mug_max_z + mug_min_z) / 2;
_mug_r_at_natch_z = handle_enabled
    ? mug_r_at_z(handle_outer_centroid[2])
    : mug_r_at_z(_natch_mid_z);
natch_1_x = handle_enabled
    ? (handle_outer_centroid[0] + _mug_r_at_natch_z) / 2
    : _mug_r_at_natch_z + plaster_thickness / 2;
natch_1_z = handle_enabled ? handle_outer_centroid[2] : _natch_mid_z;
natch_2_x = -(_mug_r_at_natch_z + plaster_thickness / 2);
natch_2_z = natch_1_z;

// Natch holes (cylindrical, for separate alignment hardware)
module seam_natch(pos) {
    translate(pos)
        rotate([90, 0, 0])
            cylinder(r = natch_radius, h = natch_radius * 2,
                     center = true, $fn = 32);
}

module seam_natches() {
    seam_natch([natch_1_x, 0, natch_1_z]);
    seam_natch([natch_2_x, 0, natch_2_z]);
}

// Integrated keys (hemisphere bumps/sockets)
module _hemisphere(r) {
    difference() {
        sphere(r = r, $fn = 32);
        translate([0, 0, -r]) cube(2 * r, center = true);
    }
}

// Teardrop half-cone: 45° cone that extends beyond the hemisphere,
// sliced to the z ≤ 0 half (matching the hemisphere dome after
// rotate([180,0,0])).  rot orients the cone before slicing.
module _teardrop_cone(r, rot) {
    _cr = sin(45) * r;
    intersection() {
        rotate(rot)
            translate([0, 0, _cr])
                cylinder(h = _cr, r1 = _cr, r2 = 0, $fn = 32);
        translate([0, 0, -500 + 0.005]) cube(1000, center = true);
    }
}

// Integrated keys — socket (unioned onto case → negative in plaster)
module seam_key_socket(pos) {
    translate(pos)
        rotate([-90, 0, 0])
            _hemisphere(_key_r_socket);
}

module seam_keys_sockets() {
    seam_key_socket([natch_1_x, 0, natch_1_z]);
    seam_key_socket([natch_2_x, 0, natch_2_z]);
}

// Integrated keys — bump (subtracted from case → positive in plaster)
module seam_key_bump(pos) {
    translate(pos)
        rotate([-90, 0, 0])
            _hemisphere(_key_r_bump);
}

module seam_keys_bumps() {
    seam_key_bump([natch_1_x, 0, natch_1_z]);
    seam_key_bump([natch_2_x, 0, natch_2_z]);
}

module case_half_a() {
    if (_use_keys) {
        union() {
            case_half(true);
            seam_keys_sockets();
        }
    } else {
        difference() {
            case_half(true);
            seam_natches();
        }
    }
}

module case_half_b() {
    difference() {
        case_half(false);
        if (_use_keys) seam_keys_bumps(); else seam_natches();
    }
}

// =====================================================================
// THREE-PART MOULD
// =====================================================================

module case_upper_half(pos_y) {
    union() {
        intersection() {
            full_walls();
            if (pos_y) clip_y_pos(); else clip_y_neg();
            clip_z_above(_foot_z);
        }
        intersection() {
            y_seam_floor(pos_y);
            clip_z_above(_foot_z);
        }
        intersection() {
            z_seam_floor(_foot_z);
            if (pos_y) clip_y_pos(); else clip_y_neg();
        }

        intersection() {
            mug_positive();
            if (pos_y) clip_y_pos(); else clip_y_neg();
            clip_z_above(_foot_z);
            full_outer_hull();
        }
    }
}

// --- Base part (rectangular box) ---
_base_x_half = max([for (p = _outer)
    let(dz = p[1] - _foot_z)
    if (abs(dz) <= plaster_thickness)
        p[0] + sqrt(plaster_thickness * plaster_thickness - dz * dz)
]);
_base_y_half = mould_y_half;
_base_z_bot = mug_min_z - plaster_thickness;

module case_base_box() {
    difference() {
        translate([-_base_x_half - wall_thickness,
                   -_base_y_half - wall_thickness,
                   _base_z_bot])
            cube([2 * (_base_x_half + wall_thickness),
                  2 * (_base_y_half + wall_thickness),
                  _foot_z - _base_z_bot]);

        translate([-_base_x_half,
                   -_base_y_half,
                   _base_z_bot - 0.1])
            cube([2 * _base_x_half,
                  2 * _base_y_half,
                  _foot_z - wall_thickness - _base_z_bot + 0.1]);
    }
}

module case_base_part() {
    union() {
        case_base_box();

        intersection() {
            mug_solid();
            clip_z_below(_foot_z);
        }
    }
}

// --- Base alignment ---
_base_natch_max_r = mug_r_at_z(_foot_z);
_base_natch_alt_y = (_base_natch_max_r + _base_y_half) / 2;
base_natch_y = max(_base_natch_max_r + 5 + natch_radius, _base_natch_alt_y);

// Natch holes (cylindrical)
module base_natch(y_pos) {
    translate([0, y_pos, _foot_z])
        cylinder(r = natch_radius, h = natch_radius * 2,
                 center = true, $fn = 32);
}

module base_natches() {
    base_natch(base_natch_y);
    base_natch(-base_natch_y);
}

// Integrated keys (base ↔ upper halves at _foot_z)
// Sockets: unioned onto base case → negative in plaster.
// Hemisphere dome -Z; teardrop cone toward Y=0 (inward on base, down on A/B).
module base_keys_sockets() {
    translate([0, base_natch_y, _foot_z]) {
        rotate([180, 0, 0]) _hemisphere(_key_r_socket);
        _teardrop_cone(_key_r_socket, [90, 0, 0]);
    }
    translate([0, -base_natch_y, _foot_z]) {
        rotate([180, 0, 0]) _hemisphere(_key_r_socket);
        _teardrop_cone(_key_r_socket, [-90, 0, 0]);
    }
}

// Bumps: subtracted from upper-half case → positive in plaster.
// Hemisphere dome -Z; teardrop cone away from Y=0 (down on A/B print orientation).
module base_keys_bumps() {
    translate([0, base_natch_y, _foot_z + _z_seam_thickness + 0.01]) {
        rotate([180, 0, 0]) _hemisphere(_key_r_bump);
        _teardrop_cone(_key_r_bump, [90, 180, 0]);
    }
    translate([0, -base_natch_y, _foot_z + _z_seam_thickness + 0.01]) {
        rotate([180, 0, 0]) _hemisphere(_key_r_bump);
        _teardrop_cone(_key_r_bump, [-90, 180, 0]);
    }
}

module case_3part_half_a() {
    if (_use_keys) {
        difference() {
            union() {
                case_upper_half(true);
                seam_keys_sockets();
            }
            base_keys_bumps();
        }
    } else {
        difference() {
            case_upper_half(true);
            seam_natches();
            base_natches();
        }
    }
}

module case_3part_half_b() {
    if (_use_keys) {
        difference() {
            case_upper_half(false);
            seam_keys_bumps();
            base_keys_bumps();
        }
    } else {
        difference() {
            case_upper_half(false);
            seam_natches();
            base_natches();
        }
    }
}

module case_base() {
    if (_use_keys) {
        union() {
            case_base_part();
            base_keys_sockets();
        }
    } else {
        difference() {
            case_base_part();
            base_natches();
        }
    }
}

// =====================================================================
// PLASTER VOLUME ESTIMATION
// =====================================================================

_vol_fn = 36;

function _profile_height(pts) =
    let(zs = [for (p = pts) p[1]])
    max(zs) - min(zs);
function _safe_sweep(pts, fn) =
    len(pts) >= 2 && _profile_height(pts) > 0.001
        ? rotate_sweep(pts, caps=true, $fn=fn)
        : EMPTY_VNF;

// Approximate outward offset of a half-profile (list of [r, z] points).
function _offset_profile(pts, off, cap_z) =
    let(
        n = len(pts),
        top_r = pts[n-1][0] + off,
        raw_top_z = pts[n-1][1] + off,
        use_top_z = is_undef(cap_z) ? raw_top_z : max(raw_top_z, cap_z)
    )
    concat(
        [[0, pts[0][1] - off]],
        [for (p = pts) [p[0] + off, p[1]]],
        use_top_z > pts[n-1][1] ? [[top_r, use_top_z]] : [],
        [[0, use_top_z]]
    );

// Clip a half-profile to z >= z_cut, interpolating at the boundary.
function _clip_profile_above(pts, z_cut) =
    let(n = len(pts))
    [for (i = [0:n-1])
        let(
            p = pts[i],
            prev = i > 0 ? pts[i-1] : undef,
            next = i < n-1 ? pts[i+1] : undef
        )
        each concat(
            (prev != undef && prev[1] < z_cut && p[1] >= z_cut)
                ? [let(t = (z_cut - prev[1]) / (p[1] - prev[1]))
                   [prev[0] + t * (p[0] - prev[0]), z_cut]]
                : [],
            p[1] >= z_cut ? [p] : [],
            (next != undef && p[1] >= z_cut && next[1] < z_cut)
                ? [let(t = (z_cut - p[1]) / (next[1] - p[1]))
                   [p[0] + t * (next[0] - p[0]), z_cut]]
                : []
        )
    ];

function _clip_profile_below(pts, z_cut) =
    let(n = len(pts))
    [for (i = [0:n-1])
        let(
            p = pts[i],
            prev = i > 0 ? pts[i-1] : undef,
            next = i < n-1 ? pts[i+1] : undef
        )
        each concat(
            (prev != undef && prev[1] > z_cut && p[1] <= z_cut)
                ? [let(t = (z_cut - prev[1]) / (p[1] - prev[1]))
                   [prev[0] + t * (p[0] - prev[0]), z_cut]]
                : [],
            p[1] <= z_cut ? [p] : [],
            (next != undef && p[1] <= z_cut && next[1] > z_cut)
                ? [let(t = (z_cut - p[1]) / (next[1] - p[1]))
                   [p[0] + t * (next[0] - p[0]), z_cut]]
                : []
        )
    ];

// --- VNF construction (low-res for speed) ---

// Mould profile as a half-profile for volume estimation (outer + tube cap)
_mould_half = concat(
    _outer,
    [[0, _tube_top_z]]
);

_vnf_mould = _safe_sweep(_mould_half, _vol_fn);
_vnf_handle = handle_enabled
    ? skin(handle_stations_extended, slices=0, caps=true, method="reindex")
    : EMPTY_VNF;

// Hull: outer profile offset by plaster_thickness, extended to inner_top_z
_hull_profile = _offset_profile(_outer, plaster_thickness, inner_top_z);
_vnf_hull = _safe_sweep(_hull_profile, _vol_fn);

_v_mould = abs(vnf_volume(_vnf_mould));
_v_handle = handle_enabled ? abs(vnf_volume(_vnf_handle)) : 0;
_v_positive = _v_mould + _v_handle;
_v_hull = abs(vnf_volume(_vnf_hull));

// --- 2-part volumes ---
_v_2part_half = (_v_hull - _v_positive) / 2;

// --- 3-part volumes ---
_outer_above = _clip_profile_above(_outer, _foot_z);
_outer_below = _clip_profile_below(_outer, _foot_z);
_hull_above = _clip_profile_above(_hull_profile, _foot_z);

_vnf_outer_above = _safe_sweep(_outer_above, _vol_fn);
_vnf_outer_below = _safe_sweep(_outer_below, _vol_fn);
_vnf_hull_above = _safe_sweep(_hull_above, _vol_fn);

// Filler tube portion above mug_max_z
_filler_above_rim = _clip_profile_above(
    [[0, _body[body_foot_idx][1]], [_split_r, _split_z], [_split_r, _tube_top_z], [0, _tube_top_z]],
    mug_max_z
);
_vnf_filler = _safe_sweep(_filler_above_rim, _vol_fn);
_v_filler = abs(vnf_volume(_vnf_filler));

_v_positive_above = abs(vnf_volume(_vnf_outer_above))
                  + _v_filler
                  + _v_handle;
_v_hull_above_vol = abs(vnf_volume(_vnf_hull_above));
_v_3part_upper_half = (_v_hull_above_vol - _v_positive_above) / 2;

// Base: rectangular box interior minus foot positive
_v_base_box_interior = (2 * _base_x_half) * (2 * _base_y_half)
                     * (_foot_z - wall_thickness - _base_z_bot);
_v_foot_positive = abs(vnf_volume(_vnf_outer_below));
_v_3part_base = _v_base_box_interior - _v_foot_positive;

// --- Slip volumes (greenware, clay-scaled) ---

// Inner profile: foot center → inner floor → inner wall → rim
_inner = [for (i = [body_foot_idx:len(_body)-1]) _body[i]];
_vnf_inner = _safe_sweep(_inner, _vol_fn);
_v_mug_capacity = abs(vnf_volume(_vnf_inner));

// Slip fill: mug interior + filler tube above the rim.
_slip_tube = [
    [_inner[len(_inner)-1][0], _split_z],
    [_split_r, _split_z],
    [_split_r, _tube_top_z],
    [0, _tube_top_z],
];
_vnf_slip_tube = _safe_sweep(_slip_tube, _vol_fn);
_v_slip_fill = _v_mug_capacity + abs(vnf_volume(_vnf_slip_tube));

// Outer profile revolve = total volume enclosed by outer surface
_vnf_outer_full = _safe_sweep(_outer, _vol_fn);
_v_mug_outer = abs(vnf_volume(_vnf_outer_full));

// Slip retained = solid clay walls = outer minus cavity
_v_slip_retained = _v_mug_outer - _v_mug_capacity;

// --- Echo volume estimates ---
echo(str(""));
echo(str("=== SLIP VOLUME (greenware) ==="));
echo(str("  Slip fill:      ", round(_v_slip_fill / 1000), " mL"));
echo(str("  Slip retained:  ", round(_v_slip_retained / 1000), " mL"));
echo(str("================================"));

if (mould_type == 2) {
    echo(str(""));
    echo(str("=== PLASTER VOLUME ESTIMATES (2-part mould) ==="));
    echo(str("  Half A:  ", round(_v_2part_half / 1000), " mL"));
    echo(str("  Half B:  ", round(_v_2part_half / 1000), " mL"));
    echo(str("  Total:   ", round(2 * _v_2part_half / 1000), " mL"));
    echo(str("================================================"));
} else if (mould_type == 3) {
    _v_3part_total = 2 * _v_3part_upper_half + _v_3part_base;
    echo(str(""));
    echo(str("=== PLASTER VOLUME ESTIMATES (3-part mould) ==="));
    echo(str("  Half A:  ", round(_v_3part_upper_half / 1000), " mL"));
    echo(str("  Half B:  ", round(_v_3part_upper_half / 1000), " mL"));
    echo(str("  Base:    ", round(_v_3part_base / 1000), " mL"));
    echo(str("  Total:   ", round(_v_3part_total / 1000), " mL"));
    echo(str("================================================"));
}

// =====================================================================
// RENDER — print-ready orientation
// =====================================================================

_hull_z_min = mug_min_z - plaster_thickness;
_hull_z_max = inner_top_z + wall_thickness;
_layout_gap = 10;

module render_2part() {
    if (render_part == "all") {
        translate([0, _hull_z_max + _layout_gap / 2, 0])
            rotate([90, 0, 0]) case_half_a();
        translate([0, -(_hull_z_max + _layout_gap / 2), 0])
            rotate([-90, 0, 0]) case_half_b();
    } else if (render_part == "half_a") {
        rotate([90, 0, 0]) case_half_a();
    } else if (render_part == "half_b") {
        rotate([-90, 0, 0]) case_half_b();
    }
}

module render_3part() {
    _half_y_extent = _hull_z_max - _foot_z;

    if (render_part == "all") {
        translate([0, _hull_z_max + _layout_gap / 2, 0])
            rotate([90, 0, 0]) case_3part_half_a();
        translate([0, -(_hull_z_max + _layout_gap / 2), 0])
            rotate([-90, 0, 0]) case_3part_half_b();

        translate([0,
                   _layout_gap / 2 + _half_y_extent
                       + _layout_gap + mould_y_half + wall_thickness,
                   _foot_z])
            rotate([180, 0, 0]) case_base();

    } else if (render_part == "half_a") {
        rotate([90, 0, 0]) case_3part_half_a();
    } else if (render_part == "half_b") {
        rotate([-90, 0, 0]) case_3part_half_b();
    } else if (render_part == "base") {
        translate([0, 0, _foot_z]) rotate([180, 0, 0]) case_base();
    }
}

if (mould_type == 2) {
    render_2part();
} else if (mould_type == 3) {
    render_3part();
}
