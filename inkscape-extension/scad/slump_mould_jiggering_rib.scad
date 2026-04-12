// Slump Mould Jiggering Rib — OpenSCAD
// Requires BOSL2: https://github.com/BelfrySCAD/BOSL2
//
// A flat template (rib) for shaping clay in a slump mould using a
// jigger arm.  The inner mug profile + actual lip shape defines the
// cutting edge.  The blade swoops up the inner wall, curves over the
// lip, and hooks down to max_x.

include <BOSL2/std.scad>

include <mug_params.scad>
include <mug_body_profile.scad>

// =====================================================================
// CLAY SHRINKAGE SCALING
// =====================================================================

_cs = clay_shrinkage_pct > 0 ? 100 / (100 - clay_shrinkage_pct) : 1;

_body = [for (p = mug_body_profile) p * _cs];

// =====================================================================
// PROFILES
// =====================================================================
// body[0] = rim (outer side), body[body_foot_idx] = foot center,
// body[last] = rim (inner side).

// Inner profile: foot -> rim
_inner = [for (i = [body_foot_idx:len(_body)-1]) _body[i]];

// Outer profile: rim -> foot (first few points are the lip/rim region)
_outer_rim_first = [for (i = [0:body_foot_idx]) _body[i]];

_outer_max_x = max([for (p = _outer_rim_first) p[0]]);

// Find the point with max_x in the outer profile (rim-first order)
_max_x_idx = [for (i = [0:len(_outer_rim_first)-1])
    if (_outer_rim_first[i][0] == _outer_max_x) i][0];

// =====================================================================
// BLADE PROFILE
// =====================================================================
// The blade path:
//   1. Starts at the foot (near axis, bottom) — inner profile
//   2. Follows the inner wall upward to the inner rim
//   3. Curves over the lip (outer rim -> down toward max_x)
//   4. Stops at max_x point

_lip_to_max_x = [for (i = [0:_max_x_idx]) _outer_rim_first[i]];

// Full blade: inner (foot->inner rim) + lip (outer rim->max_x).
// Guard against duplicate at the inner-rim / outer-rim junction:
// if the last inner point equals the first lip point, skip it.
_inner_last = _inner[len(_inner)-1];
_lip_first = _lip_to_max_x[0];
_inner_trimmed = (_inner_last[0] == _lip_first[0] && _inner_last[1] == _lip_first[1])
    ? [for (i = [0:len(_inner)-2]) _inner[i]]
    : _inner;
_blade = concat(_inner_trimmed, _lip_to_max_x);

// Blade bounds
_blade_max_x = max([for (p = _blade) p[0]]);
_blade_min_y = min([for (p = _blade) p[1]]);
_blade_max_y = max([for (p = _blade) p[1]]);

// =====================================================================
// RIB OUTLINE (single closed path with manual corner arcs)
// =====================================================================
// The rib fills the bowl's negative space: solid material between the
// axis (x = 0) and the blade (inner wall + lip), with a rectangle
// extending above and to the right for structural support / mounting.
// Bottom-left corner (foot on axis) is sharp.

_cr = 5;         // corner radius
_n_arc = 8;      // segments per corner arc
_rect_w = _blade_max_x + rib_margin;
_top_y = _blade_max_y + rib_margin;

function _arc(cx, cy, r, a0, a1, n=_n_arc) =
    [for (i = [0:n]) let(a = a0 + (a1 - a0) * i / n)
        [cx + r * cos(a), cy + r * sin(a)]];

_blade_last_y = _blade[len(_blade)-1][1];

_rib_outline_raw = concat(
    [for (i = [0:len(_blade)-1]) _blade[i]],                  // blade: foot → lip → max_x
    [[_rect_w, _blade_last_y]],                                 // horizontal right to rect edge
    _arc(_rect_w - _cr, _top_y - _cr, _cr, 0, 90),           // top-right arc (up → left)
    _arc(_cr, _top_y - _cr, _cr, 90, 180),                   // top-left arc (left → down)
    [[0, _blade[0][1]]]                                        // down to foot (sharp)
);
_rib_outline = deduplicate(_rib_outline_raw, closed = true);

// =====================================================================
// 3D EXTRUSION WITH TAPER
// =====================================================================

module slump_rib() {
    if (rib_taper > 0) {
        // Straight-skeleton taper: roof() gives each point a height equal
        // to its distance from the nearest edge.  Scale so that roof peak
        // maps to rib_thickness, then intersect with the full extrusion to
        // cap the height and preserve the full footprint at z = 0.
        intersection() {
            linear_extrude(height = rib_thickness)
                polygon(points = _rib_outline);
            scale([1, 1, rib_thickness / rib_taper])
                roof(method = "straight")
                    polygon(points = _rib_outline);
        }
    } else {
        linear_extrude(height = rib_thickness)
            polygon(points = _rib_outline);
    }
}

// =====================================================================
// RENDER
// =====================================================================

if (wheel_direction == "clockwise")
    mirror([0, 0, 1]) slump_rib();
else
    slump_rib();
