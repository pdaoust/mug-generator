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
include <mug_body_profile.scad>

// =====================================================================
// HARDCODED PARAMETERS
// =====================================================================

cone_height = 50;           // Cone height above mould (mm)
funnel_clearance = 0.5;     // Gap between neck and pouring hole (mm)

// =====================================================================
// CLAY SHRINKAGE SCALING
// =====================================================================

_cs = clay_shrinkage_pct > 0 ? 100 / (100 - clay_shrinkage_pct) : 1;

_body = [for (p = mug_body_profile) p * _cs];
_tube_h = filler_tube_height * _cs;

// =====================================================================
// DERIVED PROFILES
// =====================================================================

_outer = [for (i = [0:body_foot_idx]) _body[i]];
_split_r = _body[0][0];
_split_z = _body[0][1];
_tube_top_z = _split_z + _tube_h;

// =====================================================================
// DERIVED VALUES
// =====================================================================

inner_top_z = _tube_top_z;

// Interpolate outer radius at a given Z.
function outer_r_at_z(z) =
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

pour_hole_r = _split_r;
cone_top_r = pour_hole_r + cone_height * tan(funnel_wall_angle);

// lip_top_z: highest Z of the outer body profile
lip_top_z = _split_z;

// Vertical-tangent detection: walk the inner profile downward from
// lip_top_z.  The rim area narrows; at some point the bowl widens again.
// The lip form stops at the last narrowing node.
_inner = [for (i = [body_foot_idx:len(_body)-1]) _body[i]];

function _sort_by_z_desc(pts) =
    len(pts) <= 1 ? pts :
    let(
        pivot_z = pts[floor(len(pts) / 2)][1],
        higher = [for (p = pts) if (p[1] > pivot_z + 1e-9) p],
        equal  = [for (p = pts) if (abs(p[1] - pivot_z) <= 1e-9) p],
        lower  = [for (p = pts) if (p[1] < pivot_z - 1e-9) p]
    )
    concat(_sort_by_z_desc(higher), equal, _sort_by_z_desc(lower));

_inner_below_lip = [for (p = _inner)
    if (p[1] < lip_top_z - 0.01) p];

_inner_sorted = _sort_by_z_desc(_inner_below_lip);

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
// LIP FORM — hollow shell from mug body profile
// =====================================================================

// Lip form: the mug body shell (rotate_extrude of profile minus
// outset profile) clipped to the lip region and pour hole radius.

module mug_body_shell() {
    difference() {
        rotate_extrude()
            offset(delta = funnel_wall)
                polygon(points = _body);
        rotate_extrude()
            polygon(points = _body);
    }
}

// =====================================================================
// FUNNEL PARTS
// =====================================================================

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

// 2. Flange (depth stop)
flange_outer_r = pour_hole_r + flange_width;

module funnel_flange() {
    rotate_extrude()
        polygon(points = [
            [pour_hole_r - funnel_wall, flange_z],
            [flange_outer_r,            flange_z],
            [pour_hole_r + funnel_wall, flange_z],
            [pour_hole_r,               cone_base_z],
            [pour_hole_r - funnel_wall, cone_base_z],
        ]);
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

// 4. Lip form — the mug body shell clipped to the lip region,
//    with breather holes for slip flow.
breather_r = breather_hole_dia / 2;
breather_z = lip_top_z - breather_r;

module funnel_lip_form() {
    difference() {
        intersection() {
            mug_body_shell();
            // Clip to pouring hole radius
            cylinder(h = 2000, r = neck_r, center = true);
            // Clip to lip Z range
            translate([0, 0, (lip_top_z + lip_bottom_z) / 2])
                cube([2000, 2000, lip_top_z - lip_bottom_z], center = true);
        }
        // Breather holes
        for (i = [0:breather_hole_count - 1])
            rotate([0, 0, i * 360 / breather_hole_count])
                translate([neck_r, 0, breather_z])
                    rotate([0, -90, 0])
                        cylinder(h = funnel_wall + 0.02,
                                 r = breather_r);
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

// Flip upside down for printing, with cone top at Z=0.
translate([0, 0, cone_base_z + cone_height])
    rotate([180, 0, 0])
        pouring_funnel();
