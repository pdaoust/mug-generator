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
include <lib/handle_geom.scad>

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

_body = mug_body_polyline(mug_body_profile_bez, _cs);
_foot_idx = mug_foot_idx(_body, mug_body_profile_bez, _cs);
_tube_h = filler_tube_height;

// Lip point derived analytically from the bezpath (not from Python).
_lip_pt_scaled = lip_pt_scaled(mug_body_profile_bez, _cs);
z_lip_scaled = _lip_pt_scaled[1];
lip_r_scaled = _lip_pt_scaled[0];

// =====================================================================
// DERIVED PROFILES
// =====================================================================

_outer = [for (i = [0:_foot_idx]) _body[i]];
_split_r = lip_r_scaled;
_split_z = z_lip_scaled;
_tube_top_z = _split_z + _tube_h;
_tube_top_r = _split_r + _tube_h * tan(filler_tube_angle);

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

// Pouring hole sits at the top of the tapered case-mould filler tube,
// so its radius is the wider top of the frustum.
pour_hole_r = _tube_top_r;
cone_top_r = pour_hole_r + cone_height * tan(funnel_wall_angle);

// lip_top_z: highest Z of the outer body profile
lip_top_z = _split_z;

// Vertical-tangent detection: walk the inner profile downward from
// lip_top_z.  The rim area narrows; at some point the bowl widens again.
// The lip form stops at the last narrowing node.
_inner = [for (i = [_foot_idx:len(_body)-1]) _body[i]];

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

// Neck is a frustum matching the case-mould filler tube minus a
// uniform funnel_clearance: neck_r_bot at lip_top_z, neck_r at flange_z.
neck_r_bot = _split_r    - funnel_clearance;
neck_r     = pour_hole_r - funnel_clearance;

// =====================================================================
// LIP FORM — hollow shell from mug body profile
// =====================================================================

// Lip form: the mug body shell (rotate_extrude of profile minus
// outset profile) clipped to the lip region and pour hole radius.

module mug_body_shell() {
    difference() {
        rotate_extrude()
            intersection() {
                offset(delta = funnel_wall)
                    polygon(points = _body);
                // Clip to positive X — offset can push axis
                // points negative, which rotate_extrude rejects.
                translate([0, -500])
                    square([1000, 1000]);
            }
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

// 3. Tapered neck (inside pouring hole) — frustum that mirrors the
//    case-mould filler tube, offset inward by funnel_clearance.
module funnel_neck() {
    h = flange_z - lip_top_z;
    // Extend the neck slightly past both ends so it overlaps the
    // flange and lip form volumetrically (avoids coplanar boundary
    // faces that yield a non-manifold union).
    eps_top = 0.05;
    eps_bot = 0.05;
    h_ext = h + eps_top + eps_bot;
    slope_r = (neck_r - neck_r_bot) / h;
    r_bot_ext = neck_r_bot - slope_r * eps_bot;
    r_top_ext = neck_r     + slope_r * eps_top;
    translate([0, 0, lip_top_z - eps_bot])
        difference() {
            cyl(h = h_ext, r1 = r_bot_ext, r2 = r_top_ext,
                anchor = BOTTOM);
            translate([0, 0, -0.01])
                cyl(h = h_ext + 0.02,
                    r1 = r_bot_ext - funnel_wall,
                    r2 = r_top_ext - funnel_wall,
                    anchor = BOTTOM);
        }
}

// 4. Lip form — the mug body shell clipped to the lip region,
//    with breather holes for slip flow.
breather_r = breather_hole_dia / 2;
// Drop breather slightly below lip_top_z so the punch cylinder's top
// is not coplanar with the lip Z clip boundary.
breather_z = lip_top_z - breather_r - 0.05;

module funnel_lip_form() {
    difference() {
        intersection() {
            mug_body_shell();
            // Clip to pouring hole radius at the lip Z (tube bottom).
            cylinder(h = 2000, r = neck_r_bot, center = true);
            // Clip to lip Z range
            translate([0, 0, (lip_top_z + lip_bottom_z) / 2])
                cube([2000, 2000, lip_top_z - lip_bottom_z], center = true);
        }
        // Breather holes
        for (i = [0:breather_hole_count - 1])
            rotate([0, 0, i * 360 / breather_hole_count])
                translate([neck_r_bot, 0, breather_z])
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
// Suppressed when funnel_style is "integrated" — the funnel is then
// built into the case mould and no separate piece is needed.
if (funnel_style == "plastic")
    translate([0, 0, cone_base_z + cone_height])
        rotate([180, 0, 0])
            pouring_funnel();
