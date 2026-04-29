// Hump Mould Rib — OpenSCAD
// Requires BOSL2: https://github.com/BelfrySCAD/BOSL2
//
// A flat template (rib) for shaping clay on a hump mould by hand or using a
// jigger arm. The outer mug profile defines the cutting edge.
// The rib is oriented with rim at bottom (y = 0), foot at top.

include <BOSL2/std.scad>
include <lib/handle_geom.scad>

include <mug_params.scad>
include <mug_body_profile.scad>

// =====================================================================
// CLAY SHRINKAGE SCALING
// =====================================================================

_cs = clay_shrinkage_pct > 0 ? 100 / (100 - clay_shrinkage_pct) : 1;

_body = mug_body_polyline(mug_body_profile_bez, _cs);
_foot_idx = mug_foot_idx(_body, mug_body_profile_bez, _cs);

// =====================================================================
// OUTER PROFILE (foot-first)
// =====================================================================
// _outer goes rim -> foot.  Reverse so it goes foot -> rim,
// then flip y so the rim (opening) sits at y = 0.

_outer_rim_first = [for (i = [0:_foot_idx]) _body[i]];
_outer_unflipped = [for (i = [len(_outer_rim_first)-1:-1:0]) _outer_rim_first[i]];
_outer_flip_y = max([for (p = _outer_unflipped) p[1]]);
_outer = [for (p = _outer_unflipped) [p[0], _outer_flip_y - p[1]]];

_outer_max_x = max([for (p = _outer) p[0]]);
_outer_min_y = min([for (p = _outer) p[1]]);
_outer_max_y = max([for (p = _outer) p[1]]);

// Index of max x and min y points
_max_x_idx = [for (i = [0:len(_outer)-1])
    if (_outer[i][0] == _outer_max_x) i][0];
_min_y_idx = [for (i = [0:len(_outer)-1])
    if (_outer[i][1] == _outer_min_y) i][0];
_max_y_idx = [for (i = [0:len(_outer)-1])
    if (_outer[i][1] == _outer_max_y) i][0];

// =====================================================================
// BLADE PROFILE (anti-undercut)
// =====================================================================
// "top": foot -> max_x point -> down to rim at max_x -> axis at rim.
//        The closing L descends to the rim along max_x, then returns
//        to the axis, so the scoop covers the full area between the
//        profile and the axis.
_blade_top = concat(
    [for (i = [0:_max_x_idx]) _outer[i]],
    [[_outer_max_x, _outer_min_y]],
    [[0, _outer_min_y]]
);

// "side": traverse from min_y to max_y (decreasing index after y-flip).
_side_first = _outer[_min_y_idx];
_side_last = _outer[_max_y_idx];
_blade_side = concat(
    _side_first[0] == 0 ? [] : [[0, _outer_min_y]],
    [for (i = [_min_y_idx:-1:_max_y_idx]) _outer[i]],
    _side_last[0] == 0 ? [] : [[0, _outer_max_y]]
);

_blade = (hump_rib_direction == "side") ? _blade_side : _blade_top;

// Blade bounds
_blade_max_x = max([for (p = _blade) p[0]]);
_blade_min_y = min([for (p = _blade) p[1]]);
_blade_max_y = max([for (p = _blade) p[1]]);

// =====================================================================
// RIB OUTLINE (single closed path with manual corner arcs)
// =====================================================================

_cr = 5;         // corner radius
_n_arc = 8;      // segments per corner arc
_rect_w = _blade_max_x + rib_margin;
_rect_h = _blade_max_y - _blade_min_y + rib_margin;
_top_y = _blade_min_y + _rect_h;

function _arc(cx, cy, r, a0, a1, n=_n_arc) =
    [for (i = [0:n]) let(a = a0 + (a1 - a0) * i / n)
        [cx + r * cos(a), cy + r * sin(a)]];

_blade_last_y = _blade[len(_blade)-1][1];

_rib_outline_raw = (hump_rib_direction == "side") ?
    // Side approach: rectangle with blade reversed on the left.
    concat(
        [[0, _blade_min_y]],
        _arc(_rect_w - _cr, _blade_min_y + _cr, _cr, 270, 360),
        _arc(_rect_w - _cr, _top_y - _cr, _cr, 0, 90),
        _arc(_cr, _top_y - _cr, _cr, 90, 180),
        [[0, _blade_max_y]],
        [for (i = [len(_blade)-1:-1:0]) _blade[i]]
    ) :
    // Top approach: blade forward, rectangle wraps right and above.
    concat(
        [for (i = [0:len(_blade)-1]) _blade[i]],
        [[_rect_w, _blade_last_y]],
        _arc(_rect_w - _cr, _top_y - _cr, _cr, 0, 90),
        _arc(_cr, _top_y - _cr, _cr, 90, 180),
        [[0, _blade[0][1]]]
    );

_rib_outline = deduplicate(_rib_outline_raw, closed = true);

// =====================================================================
// 3D EXTRUSION WITH TAPER
// =====================================================================

module hump_rib() {
    if (rib_taper > 0) {
        intersection() {
            linear_extrude(height = rib_thickness)
                polygon(points = _rib_outline);
            scale([1, 1, rib_thickness / rib_taper])
                roof(method = "straight")
                    // Tiny offset round-trip cleans collinear edges on x=0
                    // that crash CGAL's straight skeleton.
                    offset(r = 0.01) offset(r = -0.01)
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
    mirror([0, 0, 1]) hump_rib();
else
    hump_rib();
