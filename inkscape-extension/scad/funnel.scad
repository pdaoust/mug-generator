// Pouring Funnel — OpenSCAD
// Requires BOSL2: https://github.com/BelfrySCAD/BOSL2
//
// A 3D-printable funnel that sits in the mould's pouring hole to guide
// slip into the mould.  The lip form at the bottom shapes the mug's rim.
//
// Four parts (unioned):
//   1. Inverted cone (above mould) — wide top narrows to pouring hole
//   2. Flange (depth stop) — rests on top of the mould surface
//   3. Cylindrical neck — fits inside the pouring hole
//   4. Lip form — shapes the mug's lip/rim

include <BOSL2/std.scad>

include <mug_params.scad>
include <mug_outer_profile.scad>
include <mug_inner_profile.scad>

// =====================================================================
// HARDCODED PARAMETERS
// =====================================================================

cone_height = 50;           // Cone height above mould (mm)
funnel_clearance = 0.5;     // Gap between neck and pouring hole (mm)

// =====================================================================
// DERIVED VALUES
// =====================================================================

inner_top_z = max([for (p = mug_inner_profile) p[1]]);

// Interpolate inner profile radius at a given Z.
// Returns the maximum radius found at that Z.
function inner_r_at_z(z) =
    let(
        prof = mug_inner_profile, n = len(prof),
        results = [for (i = [0:n-1])
            let(j = (i + 1) % n,
                z0 = prof[i][1], z1 = prof[j][1],
                zlo = min(z0, z1), zhi = max(z0, z1))
            if (zlo <= z && z <= zhi && abs(zhi - zlo) > 1e-9)
                let(t = (z - z0) / (z1 - z0))
                prof[i][0] + t * (prof[j][0] - prof[i][0])
        ]
    ) len(results) > 0 ? max(results) : prof[0][0];

pour_hole_r = inner_r_at_z(inner_top_z);
cone_top_r = pour_hole_r + cone_height * tan(funnel_wall_angle);

// lip_top_z: highest Z of the outer body profile
lip_top_z = max([for (p = mug_outer_profile) p[1]]);

// Vertical-tangent detection: walk the inner profile downward from
// lip_top_z.  The rim area narrows; at some point the bowl widens again.
// The lip form stops at the last narrowing node (just before the first
// widening).  Sort by descending Z, then find the first pair where
// radius increases going down.
function _sort_by_z_desc(pts) =
    len(pts) <= 1 ? pts :
    let(
        pivot_z = pts[floor(len(pts) / 2)][1],
        higher = [for (p = pts) if (p[1] > pivot_z + 1e-9) p],
        equal  = [for (p = pts) if (abs(p[1] - pivot_z) <= 1e-9) p],
        lower  = [for (p = pts) if (p[1] < pivot_z - 1e-9) p]
    )
    concat(_sort_by_z_desc(higher), equal, _sort_by_z_desc(lower));

_inner_below_lip = [for (p = mug_inner_profile)
    if (p[1] < lip_top_z - 0.01) p];

_inner_sorted = _sort_by_z_desc(_inner_below_lip);

// Walk from top: find the first pair where radius INCREASES going down
// (lower Z point has larger radius).  Take the higher-Z node of that pair.
_first_vtangent_z = let(
    pts = _inner_sorted,
    n = len(pts),
    hits = [for (i = [0:max(0, n - 2)])
        if (n >= 2 && pts[i + 1][0] > pts[i][0] + 0.01)
        pts[i][1]]
) len(hits) > 0 ? hits[0] : lip_top_z - 3;

lip_bottom_z = max(lip_top_z - 3, _first_vtangent_z);

neck_r = pour_hole_r - funnel_clearance;

// =====================================================================
// MUG INNER SOLID (duplicated from mould.scad to avoid use<> scoping)
// =====================================================================

_n_inner = len(mug_inner_profile);
_solid_inner_profile = concat(
    mug_inner_profile,
    [[0, mug_inner_profile[_n_inner - 1][1]],
     [0, mug_inner_profile[0][1]]]
);

module mug_inner_solid() {
    rotate_extrude() polygon(points = _solid_inner_profile);
}

// =====================================================================
// FUNNEL PARTS
// =====================================================================

// Flange sits flush with the top of the inner body (plaster mould surface).
// The printed case mould is peeled away, so wall_thickness is irrelevant here.
flange_z = inner_top_z;
cone_base_z = flange_z + funnel_wall;

// 1. Inverted cone (above mould, on top of flange)
module funnel_cone() {
    translate([0, 0, cone_base_z])
        difference() {
            cylinder(h = cone_height,
                     r1 = pour_hole_r,
                     r2 = cone_top_r);
            translate([0, 0, -0.01])
                cylinder(h = cone_height + 0.02,
                         r1 = pour_hole_r - funnel_wall,
                         r2 = cone_top_r - funnel_wall);
        }
}

// 2. Flange (depth stop) — rests on the mould top surface
module funnel_flange() {
    translate([0, 0, flange_z])
        difference() {
            cylinder(h = funnel_wall,
                     r = pour_hole_r + flange_width);
            translate([0, 0, -0.01])
                cylinder(h = funnel_wall + 0.02,
                         r = pour_hole_r - funnel_wall);
        }
}

// 3. Cylindrical neck (inside pouring hole)
module funnel_neck() {
    translate([0, 0, lip_top_z])
        difference() {
            cylinder(h = flange_z - lip_top_z,
                     r = neck_r);
            translate([0, 0, -0.01])
                cylinder(h = flange_z - lip_top_z + 0.02,
                         r = neck_r - funnel_wall);
        }
}

// 4. Lip form (shapes the mug's rim)
module funnel_lip_form() {
    intersection() {
        mug_inner_solid();
        // Clip to pouring hole radius
        cylinder(h = 2000, r = neck_r, center = true);
        // Clip to lip Z range
        translate([0, 0, (lip_top_z + lip_bottom_z) / 2])
            cube([2000, 2000, lip_top_z - lip_bottom_z], center = true);
    }
}

// =====================================================================
// ASSEMBLY
// =====================================================================

module pouring_funnel() {
    union() {
        funnel_cone();
        funnel_flange();
        funnel_neck();
        funnel_lip_form();
    }
}

pouring_funnel();
