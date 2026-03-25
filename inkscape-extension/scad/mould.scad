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
include <mug_outer_profile.scad>
include <mug_inner_profile.scad>
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

_outer = [for (p = mug_outer_profile) p * _cs];
_inner = [for (p = mug_inner_profile) p * _cs];
_hstations = handle_enabled
    ? [for (s = handle_stations) [for (p = s) p * _cs]]
    : [];
_mpoints = [for (p = mark_points) p * _cs];
_axis = mug_axis_x * _cs;
_mark_depth = mark_depth * _cs;

// =====================================================================
// DERIVED VALUES
// =====================================================================

mug_max_radius = max([for (p = _outer) p[0]]);
mug_max_z = max([for (p = _outer) p[1]]);
mug_min_z = min([for (p = _outer) p[1]]);

inner_top_z = max([for (p = _inner) p[1]]);
handle_max_y = handle_enabled
    ? max([for (s = _hstations) for (p = s) abs(p[1])])
    : 0;
mould_y_half = max(mug_max_radius, handle_max_y) + plaster_thickness;

// =====================================================================
// MUG MODULES (from mug.scad — duplicated to avoid `use` scoping issues)
// =====================================================================

module mug_outer() {
    rotate_extrude() polygon(points = _outer);
}

// Solid mug outer: polygon extended to the Z axis for a completely
// filled body of revolution (no hollow centre).
_n_outer = len(_outer);
_solid_outer_profile = concat(
    _outer,
    [[0, _outer[_n_outer - 1][1]],
     [0, _outer[0][1]]]
);

// --- Maker's mark stamp ---
// Uses polygon(points, paths) for even-odd fill — OpenSCAD handles
// holes natively via the paths parameter, no boolean difference needed.
//
// The drawn paths are the middle of the stamp.  Draft angle expands
// outward (positive offset) at z=0 and shrinks inward (negative offset)
// at z=mark_depth, using stacked slices with OpenSCAD's offset(r=...).
// This robustly handles self-intersection: tiny features simply
// collapse at higher insets instead of blowing up.

_mark_draft = _mark_depth * tan(mark_draft_angle);
_mark_half_draft = _mark_draft / 2;
_mark_slices = mark_draft_angle > 0
    ? max(2, round(_mark_depth / mark_layer_height))
    : 1;

// z=0 is the mug-surface end (expanded), z=_mark_depth is the
// deep/tip end (shrunk).  Callers position and mirror as needed.
module mark_stamp() {
    if (len(_mpoints) > 0) {
        _dz = _mark_depth / _mark_slices;
        for (i = [0:_mark_slices - 1]) {
            // +half_draft at z=0, 0 at midpoint, -half_draft at z=_mark_depth
            _r = _mark_half_draft * (1 - 2 * (i + 0.5) / _mark_slices);
            translate([0, 0, i * _dz])
                linear_extrude(height = _dz + 0.001)
                    offset(r = _r)
                        polygon(points = _mpoints, paths = mark_paths);
        }
    }
}

module _mug_outer_solid_raw() {
    rotate_extrude() polygon(points = _solid_outer_profile);
}

// Z of the mug base — used to position the maker's mark stamp.
// For foot-ring mugs this is the foot bottom (the stamp extends upward
// and only intersects the solid at the recessed base centre).
_mark_z = mug_min_z;

module mug_outer_solid() {
    if (mark_enabled && mark_inset) {
        difference() {
            _mug_outer_solid_raw();
            // z=0 (expanded) at the base centre, cutting upward.
            // render() forces CGAL evaluation of the stacked stamp
            // so the boolean difference works in F5 preview.
            translate([0, 0, _mark_z - 0.01])
                render() mark_stamp();
        }
    } else if (mark_enabled && !mark_inset) {
        union() {
            _mug_outer_solid_raw();
            // Mirror so z=0 (expanded) is at the base centre,
            // protruding downward with the tip shrunk
            translate([0, 0, _mark_z + 0.01])
                mirror([0, 0, 1])
                    mark_stamp();
        }
    } else {
        _mug_outer_solid_raw();
    }
}

// Solid mug inner: same axis-closure treatment as the outer.
// The inner profile is drawn in the SVG to include the filler tube
// (a vertical extension above the mug rim), so the revolved solid
// naturally forms the pour tube with identical faceting.
_n_inner = len(_inner);
_solid_inner_profile = concat(
    _inner,
    [[0, _inner[_n_inner - 1][1]],
     [0, _inner[0][1]]]
);

module mug_inner_solid() {
    rotate_extrude() polygon(points = _solid_inner_profile);
}

module mug_body() {
    difference() { mug_outer(); mug_inner(); }
}

module mug_inner() {
    rotate_extrude() polygon(points = _inner);
}

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

// Mug positive: outer solid + inner solid (with integrated filler hole) + handle.
module mug_positive() {
    mug_outer_solid();
    mug_inner_solid();
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
// Returns the maximum radius found at that Z (handles multi-segment hits).
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

// Split Z for the 3-part mould.  Baseline is the foot concavity Z
// (or _mark_z when a mark forces 3-part without concavity).
// Inset marks add _mark_depth so the upward-cutting stamp stays in
// the base piece.  Protruding marks extend below _mark_z and are
// already captured by the baseline.
_foot_z = (is_undef(foot_concavity_z)
        ? (mark_enabled ? _mark_z : 0)
        : foot_concavity_z * _cs)
    + (mark_enabled && mark_inset ? _mark_depth : 0);


// Handle rail projections onto the XZ plane (2D mould coordinates:
// X = 3D X, Y = 3D Z).  Inner = closest to mug (min X per station),
// outer = farthest from mug (max X per station).
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

// Closed handle outline: outer rail forward, inner rail reversed
_handle_outline_2d = handle_enabled ? concat(
    _handle_outer_2d,
    [for (i = [len(_handle_inner_2d)-1:-1:0]) _handle_inner_2d[i]]
) : [];

// =====================================================================
// 2D MOULD PRIMITIVES (in XY plane where X = 3D X, Y = 3D Z height)
// =====================================================================

// Mould interior boundary: full plaster around the mug body, half
// plaster around the handle, gap between mug and handle filled solid.
// Clipped at inner_top_z (filler tube height from the SVG inner profile).
module mould_hull_2d() {
    difference() {
        union() {
            // 1. Mug body (outer + inner profiles) with full plaster
            offset(r = plaster_thickness) {
                polygon(points = _outer);
                mirror([1, 0]) polygon(points = _outer);
                polygon(points = _inner);
                mirror([1, 0]) polygon(points = _inner);
            }

            if (handle_enabled) {
                // 2. Handle outline with half plaster
                offset(r = plaster_thickness / 2)
                    polygon(points = _handle_outline_2d);
            }

            // 3. Fill gap between mug and handle (no offset)
            polygon(points = _outer);
            mirror([1, 0]) polygon(points = _outer);
            polygon(points = _inner);
            mirror([1, 0]) polygon(points = _inner);
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
//
// All 2D→3D extrusion uses rotate([90,0,0]) + center=true, which maps:
//   2D X → 3D X,  2D Y → 3D Z (correct height)
// Centered extrusion spans symmetrically in ±Y.
// Individual halves are obtained by clipping.

_full_y = 2 * (mould_y_half + wall_thickness);

module full_walls() {
    rotate([90, 0, 0])
        linear_extrude(height = _full_y, center = true)
            mould_wall_ring_2d();
}

module full_outer_hull() {
    rotate([90, 0, 0])
        linear_extrude(height = _full_y, center = true)
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

// Y-seam floor slab: wall_thickness thick, sitting behind the Y=0 seam.
// For the +Y half the floor is in -Y territory (and vice versa).
module y_seam_floor(pos_y) {
    intersection() {
        rotate([90, 0, 0])
            linear_extrude(height = 2 * wall_thickness, center = true)
                mould_outer_hull_2d();
        if (pos_y) clip_y_neg(); else clip_y_pos();
    }
}

// Z-seam floor slab: wall_thickness thick, sitting ABOVE z_split.
// Mating surface at z_split, floor extends upward into the cavity.
module z_seam_floor(z_split) {
    intersection() {
        full_outer_hull();
        translate([0, 0, z_split + wall_thickness / 2])
            cube([2000, 2000, wall_thickness], center = true);
    }
}

// =====================================================================
// TWO-PART MOULD HALVES
// =====================================================================
//
// Each half is a bucket:
//   Floor  = Y=0 seam plane (solid slab + mug positive protrudes)
//   Walls  = wall ring clipped to ±Y
//   Open   = far-Y face (pour plaster here)

module case_half(pos_y) {
    union() {
        // Shell (walls + floor)
        intersection() {
            full_walls();
            if (pos_y) clip_y_pos(); else clip_y_neg();
        }
        y_seam_floor(pos_y);

        // Solid mug positive, clipped to this half AND the form boundary
        intersection() {
            mug_positive();
            if (pos_y) clip_y_pos(); else clip_y_neg();
            full_outer_hull();
        }
    }
}

// --- Seam natch holes (on the Y=0 plane) ---
// #1: handle side — midway between outer handle centroid and mug surface;
//     without a handle, midpoint between mug body and mould outer wall
// #2: opposite side — past the mug body at the plaster midline

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

// Half A (+Y): female seam natches (holes in the floor)
module case_half_a() {
    difference() {
        case_half(true);
        seam_natches();
    }
}

// Half B (-Y): female seam natches (holes in the floor)
module case_half_b() {
    difference() {
        case_half(false);
        seam_natches();
    }
}

// =====================================================================
// THREE-PART MOULD
// =====================================================================
//
// Upper halves: split at Y=0, clipped to Z >= _foot_z.
//   Y-seam floor + horizontal Z-seam floor at _foot_z.
// Base: simple rectangular box, open at bottom (pour opening).
//   Floor at Z = _foot_z, walls on all four sides.

module case_upper_half(pos_y) {
    union() {
        // Shell clipped to Z >= _foot_z
        // Perimeter walls
        intersection() {
            full_walls();
            if (pos_y) clip_y_pos(); else clip_y_neg();
            clip_z_above(_foot_z);
        }
        // Y=0 seam floor
        intersection() {
            y_seam_floor(pos_y);
            clip_z_above(_foot_z);
        }
        // Horizontal floor at Z = _foot_z
        intersection() {
            z_seam_floor(_foot_z);
            if (pos_y) clip_y_pos(); else clip_y_neg();
        }

        // Solid mug positive, Z >= _foot_z, this Y-half, cropped to form
        intersection() {
            mug_positive();
            if (pos_y) clip_y_pos(); else clip_y_neg();
            clip_z_above(_foot_z);
            full_outer_hull();
        }
    }
}

// --- Base part (rectangular box) ---
// Straight walls for easy mould release (no draft angle).
// Floor at _foot_z (top), open at bottom (pour opening).
// X and Y half-extents match the top parts' bounding box so the
// base sits flush under the upper halves at the Z seam.

// The offset(r=plaster_thickness) circle around each profile point
// extends horizontally at the seam plane by sqrt(pt² - dz²), where
// dz is the vertical distance from that point to _foot_z.
_base_x_half = max([for (p = _outer)
    let(dz = p[1] - _foot_z)
    if (abs(dz) <= plaster_thickness)
        p[0] + sqrt(plaster_thickness * plaster_thickness - dz * dz)
]);
_base_y_half = mould_y_half;
_base_z_bot = mug_min_z - plaster_thickness;

module case_base_box() {
    difference() {
        // Outer box
        translate([-_base_x_half - wall_thickness,
                   -_base_y_half - wall_thickness,
                   _base_z_bot])
            cube([2 * (_base_x_half + wall_thickness),
                  2 * (_base_y_half + wall_thickness),
                  _foot_z - _base_z_bot]);

        // Inner cavity: inset by wall_thickness on sides, wall_thickness
        // below _foot_z for the ceiling/floor.  Extends below outer box
        // at -Z to create the pour opening.
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

        // Solid mug foot positive inside the cavity
        intersection() {
            mug_outer_solid();
            clip_z_below(_foot_z);
        }
    }
}

// --- Base natch holes ---
// On the Z = _foot_z plane, oriented vertically (Z axis).
// Positioned along Y axis at X=0, clearing the mug body.
// Y offset = max(mug_r + clearance, midpoint between mug edge and form edge).

_base_natch_max_r = mug_r_at_z(_foot_z);
_base_natch_alt_y = (_base_natch_max_r + _base_y_half) / 2;
base_natch_y = max(_base_natch_max_r + 5 + natch_radius, _base_natch_alt_y);

module base_natch(y_pos) {
    translate([0, y_pos, _foot_z])
        cylinder(r = natch_radius, h = natch_radius * 2,
                 center = true, $fn = 32);
}

module base_natches() {
    base_natch(base_natch_y);
    base_natch(-base_natch_y);
}

// 3-part upper halves — all natches are female (holes for inserts)
module case_3part_half_a() {
    difference() {
        case_upper_half(true);
        seam_natches();
        base_natches();
    }
}

module case_3part_half_b() {
    difference() {
        case_upper_half(false);
        seam_natches();
        base_natches();
    }
}

// Base — female base natches (holes for inserts)
module case_base() {
    difference() {
        case_base_part();
        base_natches();
    }
}

// =====================================================================
// RENDER — print-ready orientation
// =====================================================================
//
// Each part is rotated so its open face points up (+Z) and its
// floor sits on the build plate (Z = 0).  Parts are spaced along Y.

_hull_z_min = mug_min_z - plaster_thickness;
_hull_z_max = inner_top_z + wall_thickness;
_layout_gap = 10;

// After rotating a half, the mug-height axis lies along Y.
// Half A  (rotate [90,0,0]):  Y ∈ [-_hull_z_max, -_foot_z]
// Half B  (rotate [-90,0,0]): Y ∈ [_foot_z, _hull_z_max]
// Shift each outward by _hull_z_max + gap/2 so the pair is
// centred on Y = 0 with _layout_gap between them.

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
        // Upper halves — beside each other along Y
        translate([0, _hull_z_max + _layout_gap / 2, 0])
            rotate([90, 0, 0]) case_3part_half_a();
        translate([0, -(_hull_z_max + _layout_gap / 2), 0])
            rotate([-90, 0, 0]) case_3part_half_b();

        // Base — flipped, placed after Half A along +Y
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
