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

// --- Render control ---
render_part = "all";   // "all", "half_a", "half_b", "base"
explode_gap = 20;

// =====================================================================
// DERIVED VALUES
// =====================================================================

mug_max_radius = max([for (p = mug_outer_profile) p[0]]);
mug_max_z = max([for (p = mug_outer_profile) p[1]]);
mug_min_z = min([for (p = mug_outer_profile) p[1]]);

inner_top_z = max([for (p = mug_inner_profile) p[1]]);
handle_max_y = max([for (s = handle_stations) for (p = s) abs(p[1])]);
mould_y_half = max(mug_max_radius, handle_max_y) + plaster_thickness;

// =====================================================================
// MUG MODULES (from mug.scad — duplicated to avoid `use` scoping issues)
// =====================================================================

module mug_outer() {
    rotate_extrude() polygon(points = mug_outer_profile);
}

// Solid mug outer: polygon extended to the Z axis for a completely
// filled body of revolution (no hollow centre).
_n_outer = len(mug_outer_profile);
_solid_outer_profile = concat(
    mug_outer_profile,
    [[0, mug_outer_profile[_n_outer - 1][1]],
     [0, mug_outer_profile[0][1]]]
);

module mug_outer_solid() {
    rotate_extrude() polygon(points = _solid_outer_profile);
}

// Solid mug inner: same axis-closure treatment as the outer.
// The inner profile is drawn in the SVG to include the filler tube
// (a vertical extension above the mug rim), so the revolved solid
// naturally forms the pour tube with identical faceting.
_n_inner = len(mug_inner_profile);
_solid_inner_profile = concat(
    mug_inner_profile,
    [[0, mug_inner_profile[_n_inner - 1][1]],
     [0, mug_inner_profile[0][1]]]
);

module mug_inner_solid() {
    rotate_extrude() polygon(points = _solid_inner_profile);
}

module mug_body() {
    difference() { mug_outer(); mug_inner(); }
}

module mug_inner() {
    rotate_extrude() polygon(points = mug_inner_profile);
}

function nudge_radial(pts, axis_x, amount) =
    [for (p = pts)
        let(dx = p[0] - axis_x, dy = p[1],
            r = norm([dx, dy]),
            s = r > 0.001 ? (r + amount) / r : 1)
        [axis_x + dx * s, dy * s, p[2]]
    ];

handle_stations_extended = concat(
    [nudge_radial(handle_stations[0], mug_axis_x, -1)],
    handle_stations,
    [nudge_radial(handle_stations[len(handle_stations)-1], mug_axis_x, -1)]
);

module handle() {
    skin(handle_stations_extended, slices=0, caps=true, method="reindex");
}

// Mug positive: outer solid + inner solid (with integrated filler hole) + handle.
module mug_positive() {
    mug_outer_solid();
    mug_inner_solid();
    handle();
}

// Centroid of outermost handle points (max X per station) —
// approximates the outer handle rail for natch placement.
_outer_handle_pts = [for (s = handle_stations)
    let(xs = [for (p = s) p[0]],
        mx = max(xs),
        candidates = [for (p = s) if (abs(p[0] - mx) < 0.01) p])
    candidates[0]
];
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

_foot_z = is_undef(foot_concavity_z) ? 0 : foot_concavity_z;

// Handle rail projections onto the XZ plane (2D mould coordinates:
// X = 3D X, Y = 3D Z).  Inner = closest to mug (min X per station),
// outer = farthest from mug (max X per station).
_handle_inner_2d = [for (s = handle_stations)
    let(xs = [for (p = s) p[0]],
        mn = min(xs),
        pts = [for (p = s) if (abs(p[0] - mn) < 0.01) p])
    [pts[0][0], pts[0][2]]
];

_handle_outer_2d = [for (s = handle_stations)
    let(xs = [for (p = s) p[0]],
        mx = max(xs),
        pts = [for (p = s) if (abs(p[0] - mx) < 0.01) p])
    [pts[0][0], pts[0][2]]
];

// Closed handle outline: outer rail forward, inner rail reversed
_handle_outline_2d = concat(
    _handle_outer_2d,
    [for (i = [len(_handle_inner_2d)-1:-1:0]) _handle_inner_2d[i]]
);

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
                polygon(points = mug_outer_profile);
                mirror([1, 0]) polygon(points = mug_outer_profile);
                polygon(points = mug_inner_profile);
                mirror([1, 0]) polygon(points = mug_inner_profile);
            }

            // 2. Handle outline with half plaster
            offset(r = plaster_thickness / 2)
                polygon(points = _handle_outline_2d);

            // 3. Fill gap between mug and handle (no offset)
            polygon(points = mug_outer_profile);
            mirror([1, 0]) polygon(points = mug_outer_profile);
            polygon(points = mug_inner_profile);
            mirror([1, 0]) polygon(points = mug_inner_profile);
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
// #1: handle side — midway between outer handle centroid and mug surface
// #2: opposite side — past the mug body at the plaster midline

mug_r_at_outer_handle = mug_r_at_z(handle_outer_centroid[2]);
natch_1_x = (handle_outer_centroid[0] + mug_r_at_outer_handle) / 2;
natch_1_z = handle_outer_centroid[2];
natch_2_x = -(mug_r_at_outer_handle + plaster_thickness / 2);
natch_2_z = handle_outer_centroid[2];

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

// --- Base part (simple rectangular box) ---
// No draft angle — straight walls for easy mould release.
// Floor at _foot_z (top), open at bottom (pour opening).

_base_half_xy = mug_max_radius + plaster_thickness;
_base_z_bot = mug_min_z - plaster_thickness;

module case_base_box() {
    difference() {
        // Outer box
        translate([-_base_half_xy - wall_thickness,
                   -_base_half_xy - wall_thickness,
                   _base_z_bot])
            cube([2 * (_base_half_xy + wall_thickness),
                  2 * (_base_half_xy + wall_thickness),
                  _foot_z - _base_z_bot]);

        // Inner cavity: inset by wall_thickness on sides, wall_thickness
        // below _foot_z for the ceiling/floor.  Extends below outer box
        // at -Z to create the pour opening.
        translate([-_base_half_xy,
                   -_base_half_xy,
                   _base_z_bot - 0.1])
            cube([2 * _base_half_xy,
                  2 * _base_half_xy,
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
_form_inner_edge_y = min(_base_half_xy, mould_y_half);
_base_natch_alt_y = (_base_natch_max_r + _form_inner_edge_y) / 2;
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
// RENDER
// =====================================================================

_hull_z_min = mug_min_z - plaster_thickness;

module render_2part() {
    if (render_part == "all") {
        translate([0,  explode_gap, 0]) case_half_a();
        translate([0, -explode_gap, 0]) case_half_b();
    } else if (render_part == "half_a") {
        case_half_a();
    } else if (render_part == "half_b") {
        case_half_b();
    }
}

module render_3part() {
    if (render_part == "all") {
        translate([0,  explode_gap, 0]) case_3part_half_a();
        translate([0, -explode_gap, 0]) case_3part_half_b();
        translate([0, 0, -(explode_gap + abs(_hull_z_min))]) case_base();
    } else if (render_part == "half_a") {
        case_3part_half_a();
    } else if (render_part == "half_b") {
        case_3part_half_b();
    } else if (render_part == "base") {
        case_base();
    }
}

if (mould_type == 2) {
    render_2part();
} else if (mould_type == 3) {
    render_3part();
}
