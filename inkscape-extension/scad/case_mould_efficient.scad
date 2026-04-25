// Case Mould Generator (plaster-efficient, peelable) — OpenSCAD
// Requires BOSL2: https://github.com/BelfrySCAD/BOSL2
//
// Thin-walled printed case mould: the mug is wrapped in a plaster
// chamber of thickness ``plaster_thickness`` which is enclosed in a
// printed shell of thickness ``wall_thickness``.  The shell is split
// at the A/B seam (Y = 0), and optionally at a horizontal Z-seam
// just below the foot inflection when the mug has a foot concavity
// or an inset maker's mark (both of which need a separate base part).

include <BOSL2/std.scad>
include <BOSL2/skin.scad>

include <mug_params.scad>
include <mug_body_profile.scad>
include <handle_stations_mould.scad>
include <mark_polygon.scad>

epsilon = 0.01;

// Greenware compensation — the mug geometry is stored at fired size
// and scaled up so that firing shrinkage lands on the drawn size.
// Mould construction parameters (wall_thickness, plaster_thickness,
// natch_radius) are NOT scaled.
_cs = clay_shrinkage_pct > 0 ? 100 / (100 - clay_shrinkage_pct) : 1;

// Handle station arrays are emitted by the Python generator already at
// greenware (cs-scaled) size, with mould offsets (wall_thickness)
// applied unscaled.  They are consumed as-is by skin() for the two
// body-level variants.  The two shell-level variants are synthesized
// in SCAD as a fat circular tube via path_sweep2d along the emitted
// handle midline, bypassing the hull-chain / skin bottleneck.
_hstations_body_pos   = handle_stations_body_positive;
_hstations_body_inner = handle_stations_body_inner_wall;

// =====================================================================
// CLOSED HALF-PROFILE
// =====================================================================
// Walks mug_body_profile from the lip (index 0) down to the foot
// inflection point (body_foot_inflection_idx), scales every coordinate
// by _cs, then closes the polygon with three axis-adjacent legs so
// offset() treats it as a closed region.  Any foot concavity below
// body_foot_inflection_idx is discarded — it lives in the base part
// instead.

// bottom_extend > 0 sinks the polygon's bottom closure below z_min by
// that distance.  mug_inner_wall_solid uses this so that after inward
// offset its revolved floor sits below the A/B clip plane at
// z_min - wall_thickness/2 — otherwise the inward-offset floor rides
// up to z_min + wt and a 1.5*wt-thick spurious plaster floor remains
// in the A/B diff.  Other callers pass 0 and get the original closure.
function scaled_closed_profile(bottom_extend = 0,
                               profile = mug_body_profile,
                               inflection_idx = body_foot_inflection_idx) =
    let(
        raw = [for (i = [0:inflection_idx])
                 [profile[i][0] * _cs,
                  profile[i][1] * _cs]],
        z_bot = z_min_scaled - bottom_extend,
        foot_r = raw[len(raw) - 1][0],
        // raw runs from (lip_r, z_lip) down to (foot_r, z_min).  Append
        // axis closure: drop to z_bot along the foot wall, run in along
        // the bottom, up the axis, and back across the top.
        closed = bottom_extend > 0
            ? concat(raw,
                     [[foot_r, z_bot],
                      [0,      z_bot],
                      [0,      z_lip_scaled]])
            : concat(raw,
                     [[0, z_min_scaled],
                      [0, z_lip_scaled]])
    ) closed;

// BOSL2 offset() on a closed polygon handles self-intersection and
// miter cases for us.  Large outsets (plaster_thickness + wall_thickness
// ≈ 31 mm) will warn in preview if a profile is too aggressively
// curved — that's a drawing problem, not a bug here.
//
// Outsetting a closed polygon rounds the axis-closure corners outward
// (into negative X).  Clamping those rounded points to X=0 produces a
// long run of collinear points on the axis; revolving such a polygon
// creates zero-area degenerate triangles at the axis that CGAL's Nef
// union asserts on.  After clamping, drop any point whose neighbours
// are also at X=0 — this preserves the run's endpoints (the real
// corners of the axis-return leg) and discards only the axis-interior
// stacking.
_axis_eps = 0.001;
function _is_on_axis(p) = p[0] <= _axis_eps;
function clamp_to_axis(pts) =
    let(
        clamped = [for (p = pts) [max(0, p[0]), p[1]]],
        n = len(clamped)
    )
    [for (i = [0:n-1])
        let(
            prev_on = _is_on_axis(clamped[(i - 1 + n) % n]),
            cur_on  = _is_on_axis(clamped[i]),
            next_on = _is_on_axis(clamped[(i + 1) % n])
        )
        if (!(cur_on && prev_on && next_on)) clamped[i]];

// After an inward offset (d < 0), the axis-closure leg translates
// rigidly from x=0 to x≈|d|.  Revolved as-is, that translated leg
// becomes a spurious r=|d| stub cylinder on the axis.  Snap points
// that lie on exactly the shifted leg (within _axis_eps) back to x=0.
// The band must be narrow — a wider snap would pull sloped wall points
// onto the axis and collapse real geometry.
function snap_axis_stub(pts, d) =
    d >= 0 ? pts
    : let(inset = -d)
      [for (p = pts)
          [abs(p[0] - inset) < _axis_eps ? 0 : p[0], p[1]]];

function offset_profile(d, bottom_extend = 0,
                        profile = mug_body_profile,
                        inflection_idx = body_foot_inflection_idx) =
    clamp_to_axis(snap_axis_stub(
        d == 0 ? scaled_closed_profile(bottom_extend, profile, inflection_idx)
               : offset(scaled_closed_profile(bottom_extend, profile,
                                              inflection_idx),
                        r = d, closed = true),
        d));

module revolve(d, bottom_extend = 0) {
    rotate_extrude(angle = 360, convexity = 4)
        polygon(offset_profile(d, bottom_extend));
}

// =====================================================================
// DERIVED SHELL RADII AT Z_MIN
// =====================================================================
// The offset polygon's outer boundary at z = z_min is NOT simply
// foot_r + d: wherever the mug body tapers near the foot (narrows
// going down), the outward-perpendicular normal there has a downward
// component, so the offset polygon's right side crosses z_min at a
// noticeably larger x than an axis-parallel shift would predict.
// Derive base_outer_r and base_inner_r from the actual offset
// polygons so the base cylinder matches A/B's outer radius at the
// z seam by construction.  These overrides shadow the values passed
// in from mug_params.scad (which uses the naive additive formula).

function _offset_x_at_z(pts, z) =
    let(n = len(pts),
        xs = [for (i = [0:n-1])
                let(a = pts[i], b = pts[(i + 1) % n],
                    ya = a[1], yb = b[1])
                if ((ya - z) * (yb - z) <= 0 && abs(ya - yb) > 1e-9)
                    a[0] + (b[0] - a[0]) * (z - ya) / (yb - ya)])
    max([for (x = xs) if (x > 0) x]);

// Lazy: evaluated at use time so top-level variable resolution
// completes first (mug_body_profile, _cs, plaster_thickness etc.).
// Shell's actual offset polygon uses the coarse profile, so derive base
// radii from the same polygon to keep the A/B/base seam consistent.
function base_outer_r_derived() =
    _offset_x_at_z(offset_profile(plaster_thickness + wall_thickness, 0,
                                  mug_body_profile_shell,
                                  body_foot_inflection_idx_shell),
                   z_min_scaled);
function base_inner_r_derived() =
    _offset_x_at_z(offset_profile(plaster_thickness, 0,
                                  mug_body_profile_shell,
                                  body_foot_inflection_idx_shell),
                   z_min_scaled);

// =====================================================================
// FILLER TUBE
// =====================================================================
// A frustum sitting atop the body positive at z_lip, centred on the
// revolve axis.  Two halves: the outer frustum unions with the body
// positive, the inner frustum unions with the body inner wall and
// sinks ``wall_thickness + epsilon`` below z_lip so no roof forms
// over the mug cavity when the inner-wall solid is differenced out.

module filler_tube_outer() {
    // Sink the bottom below z_lip by epsilon so it overlaps the revolve
    // rather than sharing a coincident disc face at z=z_lip — coincident
    // faces trip CGAL Nef union (applyUnion3D assertion).
    r_bot = lip_r_scaled;
    h = filler_tube_height + epsilon;
    r_top = r_bot + h * tan(filler_tube_angle);
    translate([0, 0, z_lip_scaled - epsilon])
        cyl(h = h, r1 = r_bot, r2 = r_top, anchor = BOTTOM);
}

module filler_tube_inner() {
    r_bot = lip_r_scaled - wall_thickness;
    h = filler_tube_height + wall_thickness + 2 * epsilon;
    r_top = r_bot + h * tan(filler_tube_angle);
    translate([0, 0, z_lip_scaled - wall_thickness - epsilon])
        cyl(h = h, r1 = r_bot, r2 = r_top, anchor = BOTTOM);
}

// =====================================================================
// HANDLE SWEEPS
// =====================================================================
// Body variants (positive, inner wall) use skin() over the emitted
// per-station cross-sections — their profile shrinks and grows along
// the handle as drawn and must be preserved for the final wall and
// cavity shape.  An extra snap_to_mug endpoint is prepended/appended
// so the skin's endcaps sit *inside* the mug body revolve, giving CGAL
// a clean boolean union.
//
// Shell variants (outset by plaster_thickness ± wall_thickness) are
// approximated as a fat circular tube swept along the handle midline.
// path_sweep2d resolves local self-intersections in the sweep
// internally via offset(), which CGAL handles without asserting.
// Using a circle is safe because a ~30 mm outset of any reasonable
// handle cross-section is already nearly axisymmetric and hidden
// inside plaster.

function _centroid_station(pts) =
    let(n = len(pts))
    [for (j = [0:2])
        let(s = [for (p = pts) p[j]]) s * [for (_ = s) 1] / n];

// Radially shift the whole station so its centroid sits ``overshoot``
// mm inside the variant's revolve surface (mug_r + target_offset).
// The variant offset matters because mug_inner_wall's revolve is
// inset by wall_thickness — without target_offset the snap lands on
// the bare mug surface and the union with revolve(-wt) trips a CGAL
// Nef assertion.
function snap_to_mug(pts, axis_x, target_offset = 0, overshoot = 0.5) =
    let(
        c = _centroid_station(pts),
        cdx = c[0] - axis_x,
        cdy = c[1],
        cr = norm([cdx, cdy]),
        dir_x = cr > 0.001 ? cdx / cr : 1,
        dir_y = cr > 0.001 ? cdy / cr : 0,
        // Project each point onto the centroid-radial direction; the
        // worst offender is what we need to tuck inside target_r.
        proj = [for (p = pts) (p[0] - axis_x) * dir_x + p[1] * dir_y],
        max_r = max(proj),
        z_max = max([for (p = pts) p[2]]),
        z_min = min([for (p = pts) p[2]]),
        mug_r = min(_mug_r_at_z(z_max), _mug_r_at_z(z_min), _mug_r_at_z(c[2])),
        target_r = mug_r + target_offset - overshoot,
        shift = max(0, max_r - target_r)
    )
    [for (p = pts)
        [p[0] - shift * dir_x, p[1] - shift * dir_y, p[2]]];

// True when the cross-section dips into the mug body (any point
// closer to the axis than the bare mug surface).  Mid-handle
// stations sit entirely outside the body and are left alone;
// near-attachment stations straddle the surface and need to be
// snapped inside the variant's target revolve to avoid poking past
// the body_positive handle.
function _station_overlaps_mug(pts, axis_x) =
    let(
        radii = [for (p = pts) norm([p[0] - axis_x, p[1]])],
        z_max = max([for (p = pts) p[2]]),
        z_min = min([for (p = pts) p[2]]),
        mug_r = min(_mug_r_at_z(z_max), _mug_r_at_z(z_min))
    )
    min(radii) < mug_r;

// snap_overlap=true tucks any station that overlaps the variant's
// target revolve surface inside it (mug_r + target_offset - overshoot).
// "Overlap" means the cross-section's innermost radial point lies
// inside that surface — i.e. the station is actually intersecting the
// body. Mid-handle stations sit entirely outside the body and are
// left untouched. Used by mug_inner_wall_solid: the wt-inset revolve
// is smaller than the drawn handle's attachment cross-section, so the
// whole near-endcap region must be pushed inside revolve(-wt) to keep
// the inner wall fully behind body_positive. Slightly distorts wall
// thickness near attachment — acceptable for any reasonable handle.
module handle_skin(station_array, target_offset = 0, snap_overlap = false) {
    if (handle_enabled && len(station_array) > 1) {
        n = len(station_array);
        body = snap_overlap
            ? [for (s = station_array)
                   _station_overlaps_mug(s, mug_axis_x)
                       ? snap_to_mug(s, mug_axis_x, target_offset)
                       : s]
            : station_array;
        extended = concat(
            [snap_to_mug(body[0],     mug_axis_x, target_offset)],
            body,
            [snap_to_mug(body[n - 1], mug_axis_x, target_offset)]);
        skin(extended, slices = 0, caps = true, method = "reindex");
    }
}

// Midline sweep with a circular cross-section.  path_sweep2d's path
// lies in its native XY plane; the shape's Y maps to the output's Z.
// We pass the handle midline (mug-frame (x, z)) as the 2D path, then
// rotate the resulting polyhedron 90° about X so the path ends up in
// the mug XZ plane and the tube extends symmetrically about Y=0.
// The tube lives inside plaster and its facet count dominates shell
// render time; force $fn=8 (45° octagonal cross-section) so the sweep
// has the coarsest tessellation that still looks circular after Nef.
module handle_shell_sweep(r) {
    if (handle_enabled && len(handle_midline_xz) > 1)
        rotate([90, 0, 0])
            path_sweep2d(circle(r = r, $fn = 8),
                         handle_midline_xz);
}

// =====================================================================
// FOUR COMPOSITE SOLIDS
// =====================================================================
module mug_positive_solid() {
    union() {
        revolve(0);
        filler_tube_outer();
        handle_skin(_hstations_body_pos);
    }
}

// The inward-offset profile's horizontal bottom closure rides up to
// z_min + wt after offsetting, leaving a 1.5*wt-thick spurious plaster
// floor in the A/B diff (from the clip plane at z_min - wt/2 up to
// z_min + wt).  Extending the pre-offset bottom by 1.5*wt + epsilon
// puts the post-offset floor at z_min - wt/2 - epsilon, just below the
// clip plane, so the A/B diff consumes it entirely.
_inner_wall_bottom_extend = 1.5 * wall_thickness + epsilon;

module mug_inner_wall_solid() {
    // The revolve + filler_tube_inner pair shares a face along their
    // common axis at the lip; combined with the handle skin, CGAL's
    // 3-way Nef union trips a degenerate-intersection assertion.
    // A render() barrier around the axisymmetric pair forces it to be
    // resolved into a single Nef before the skin is added.
    union() {
        render()
            union() {
                revolve(-wall_thickness, bottom_extend = _inner_wall_bottom_extend);
                filler_tube_inner();
            }
        handle_skin(_hstations_body_inner, target_offset = -wall_thickness, snap_overlap = true);
    }
}

// Both shell solids are capped at the top of the filler tube so plaster
// can be poured in through the filler opening: the mug positive's inner
// filler tube extends above this cap and carves the pour path through to
// the mug cavity.
_shell_top_z = z_lip_scaled + filler_tube_height;

// Shell and outer-shell are the large plaster-cavity surfaces; their
// angular tessellation dominates render time but their fidelity is not
// visible on the final print (they're hidden inside plaster).  Force
// $fa=30 on the revolve here to coarsen the angular facet count.  The
// handle shell is synthesized as a circular-tube path_sweep2d.
_shell_fa = 45;

module shell_solid_geom() {
    difference() {
        union() {
            rotate_extrude(angle = 360, convexity = 4,
                           $fa = _shell_fa, $fn = 0, $fs = 2)
                polygon(offset_profile(plaster_thickness, 0,
                                       mug_body_profile_shell,
                                       body_foot_inflection_idx_shell));
            handle_shell_sweep(handle_shell_r);
        }
        half_space_z_pos(_shell_top_z);
    }
}

module shell_outer_wall_solid() {
    difference() {
        union() {
            rotate_extrude(angle = 360, convexity = 4,
                           $fa = _shell_fa, $fn = 0, $fs = 2)
                polygon(offset_profile(plaster_thickness + wall_thickness, 0,
                                       mug_body_profile_shell,
                                       body_foot_inflection_idx_shell));
            handle_shell_sweep(handle_shell_outer_r);
        }
        half_space_z_pos(_shell_top_z);
    }
}

// =====================================================================
// HALF-SPACE HELPERS
// =====================================================================
// Large cubes used to slice the composite solids at the A/B seam
// (Y = 0 plane) and, when ``needs_base`` is true, at the Z seam
// (z = z_min_scaled plane).

big = 2000;

module half_space_y_pos(y_cut) {
    translate([-big / 2, y_cut, -big / 2])
        cube([big, big, big]);
}

module half_space_z_pos(z_cut) {
    translate([-big / 2, -big / 2, z_cut])
        cube([big, big, big]);
}

// =====================================================================
// A/B RAW PART
// =====================================================================
// Each half is an independently-castable half-donut cup: its own floor
// at the bottom, its own seam wall at Y=0, its own half-shell skin.
// Outer_half extends wall_thickness past the seam plane (Y ≥ −wt) and
// (wall_thickness / 2) past the z_min plane (Z ≥ z_min − wt/2), giving
// the seam wall and the floor their respective thicknesses.  Inner_half
// is flush at Y=0 and Z=z_min.  Subtraction leaves a wt-thick seam wall
// and a (wt/2)-thick floor — independent of ``needs_base``, since each
// half must hold plaster on its own when poured.

_ab_floor_thickness = wall_thickness / 2;

module ab_raw() {
    difference() {
        intersection() {
            difference() {
                shell_outer_wall_solid();
                mug_inner_wall_solid();
            }
            half_space_y_pos(-wall_thickness);
            half_space_z_pos(z_min_scaled - _ab_floor_thickness);
        }
        intersection() {
            difference() {
                shell_solid_geom();
                mug_positive_solid();
            }
            half_space_y_pos(0);
            half_space_z_pos(z_min_scaled);
        }
    }
}

module a_part_raw() { ab_raw(); }
module b_part_raw() { mirror([0, 1, 0]) ab_raw(); }

// =====================================================================
// REGISTRATION FEATURES
// =====================================================================
// Three A/B seam features (all on Y=0 plane):
//   F1 opposite-side upper: Z just inside filler tube; -X
//   F2 opposite-side lower: Z just inside foot; -X
//   F3 handle-side mid: Z mid-body; +X, halfway between the handle's
//      outer edge at that Z and the shell outer wall
// When needs_base, two Z-seam features on z = z_min_scaled plane at ±Y.
// The handle-side feature previously sat directly below the handle, too
// close to its lower end when the handle shape made that region tight.

_use_keys = (alignment_type == "keys");
_key_tol_half = _use_keys ? key_tolerance / 2 : 0;
_key_r_bump   = natch_radius - _key_tol_half;
_key_r_socket = natch_radius + _key_tol_half;

// Walk the scaled body profile to interpolate mug radius at z. The
// profile runs lip → foot inflection; z is monotone decreasing.
function _mug_r_at_z(z) =
    let(
        prof = [for (i = [0:body_foot_inflection_idx])
                  [mug_body_profile[i][0] * _cs,
                   mug_body_profile[i][1] * _cs]],
        n = len(prof),
        // Clamp to endpoints.
        zc = max(min(z, prof[0][1]), prof[n-1][1])
    )
    [for (i = [0:n-2])
        if ((prof[i][1] >= zc && prof[i+1][1] <= zc)
         || (prof[i][1] <= zc && prof[i+1][1] >= zc))
            let(
                dz = prof[i+1][1] - prof[i][1],
                t = abs(dz) < epsilon ? 0 : (zc - prof[i][1]) / dz
            ) prof[i][0] + t * (prof[i+1][0] - prof[i][0])
    ][0];

// Inner shell radius at z = mug_r + plaster_thickness (along horizontal,
// exact for vertical walls; close enough for gently tapered walls).
function _feature_x_at_z(z) = _mug_r_at_z(z) + plaster_thickness / 2;

_f1_z = z_lip_scaled + filler_tube_height - plaster_thickness / 2;
_f2_z = z_min_scaled + (needs_base ? wall_thickness : 0) + plaster_thickness / 2;
_f3_z = (z_min_scaled + z_lip_scaled) / 2;

// Handle outer +X extent near z: pick the handle station whose centroid
// z is closest to the target and return the max x of its points.  The
// shell outer wall on the handle side is at (that max x + plaster_
// thickness), so halfway between handle and shell is (+ plaster/2).
function _argmin(arr) =
    let(m = min(arr))
    [for (i = [0:len(arr)-1]) if (arr[i] == m) i][0];

function _handle_outer_x_at_z(z) =
    let(
        stations = _hstations_body_pos,
        zs = [for (s = stations)
                let(sum_z = [for (p = s) p[2]] * [for (_ = s) 1])
                sum_z / len(s)],
        i = _argmin([for (zi = zs) abs(zi - z)])
    ) max([for (p = stations[i]) p[0]]);

// Positioning rule: treat each feature as a 2r × 2r × r bounding
// cube centred at the feature's placement point.  Position so that
// the TOP-surface centroid (z = centre_z + natch_radius / 2) sits
// halfway between the body positive radius and the shell radius at
// that Z.  This shifts features outward where the mug flares above
// the foot, preventing the z-seam natch from tucking under the mug
// body and the seam natches from biting into the mug wall.
_f_top_dz = natch_radius / 2;

_handle_side_feature_x = (handle_enabled
                          && len(_hstations_body_pos) > 0)
    ? _handle_outer_x_at_z(_f3_z + _f_top_dz) + plaster_thickness / 2
    :  _feature_x_at_z(_f3_z + _f_top_dz);

_f1_pos = [-_feature_x_at_z(_f1_z + _f_top_dz), 0, _f1_z];
_f2_pos = [-_feature_x_at_z(_f2_z + _f_top_dz), 0, _f2_z];
_f3_pos = [ _handle_side_feature_x,              0, _f3_z];

// Z-seam features: base and A/B are separate parts with their own
// internal Z frames, so features live at each part's floor plane.
// A/B floor inner plane sits at z_min_scaled (the foot-level plane);
// base's top-floor plane sits at _cavity_floor_z = z_min_scaled
// - plaster_thickness.  Y offset is shared so both parts mate when
// aligned: halfway between body radius and shell radius at the foot.
_zs_y = _feature_x_at_z(z_min_scaled + natch_radius);
_zs_base_z = z_min_scaled - plaster_thickness;

// A/B z-seam: single natch on the +Y side (B gets mirrored).
_zs_ab_pos = [0, _zs_y, z_min_scaled];

// Base z-seam: two natches, ±Y, on the base top-floor plane.
_zs1_base_pos = [0,  _zs_y, _zs_base_z];
_zs2_base_pos = [0, -_zs_y, _zs_base_z];

// --- Primitives ---
module _natch_cyl(r, h) {
    cylinder(r = r, h = h, center = true, $fn = 32);
}

module _hemisphere(r) {
    difference() {
        sphere(r = r, $fn = 8);
        translate([0, 0, -r]) cube(2 * r, center = true);
    }
}

module _teardrop_cone(r, rot) {
    _cr = sin(45) * r;
    intersection() {
        rotate(rot)
            translate([0, 0, _cr])
                cylinder(h = _cr, r1 = _cr, r2 = 0, $fn = 32);
        translate([0, 0, -500 + 0.005]) cube(1000, center = true);
    }
}

// Seam natch: cylinder perpendicular to Y=0 plane.
module _seam_natch(pos) {
    translate(pos)
        rotate([90, 0, 0])
            _natch_cyl(natch_radius, natch_radius * 2);
}

// Seam key: hemisphere + optional teardrop, pointing into +Y (socket on A)
// or mirrored to -Y (bump on B done via mirror of whole part).
// For the half-split efficient mould, each part has seam-wall material
// on only one side of Y=0.  Using a full sphere (instead of a hemisphere)
// lets the -Y half fuse with A's seam wall while the +Y half protrudes
// as the mating bump.  On B we subtract a smaller sphere to form the
// matching recess in the mating face.
module _seam_key_socket(pos) {
    translate(pos) sphere(r = _key_r_socket, $fn = 32);
}
module _seam_key_bump(pos) {
    translate(pos) sphere(r = _key_r_bump, $fn = 32);
}

// Z-seam natch: vertical cylinder crossing z = z_min_scaled plane.
module _zseam_natch(pos) {
    translate(pos) _natch_cyl(natch_radius, natch_radius * 2);
}
// Z-seam keys: same sphere approach as A/B seam — upper halves have
// bumps extending into -Z (toward the base part); base part carries
// the sockets.
module _zseam_key_socket(pos) {
    translate(pos) sphere(r = _key_r_socket, $fn = 32);
}
module _zseam_key_bump(pos) {
    translate(pos) sphere(r = _key_r_bump, $fn = 32);
}

// --- Feature groupings (A-side geometry; B-side uses mirror of whole part) ---
// A-side convention: sockets are keys on A (positive union → plaster recess),
// bumps live on B (which is mirror of A with bumps substituted).  Natches are
// symmetric — same cylinder on both halves.

module ab_seam_natches() {
    _seam_natch(_f1_pos);
    _seam_natch(_f2_pos);
    _seam_natch(_f3_pos);
}

module ab_seam_key_sockets() {
    _seam_key_socket(_f1_pos);
    _seam_key_socket(_f2_pos);
    _seam_key_socket(_f3_pos);
}

module ab_seam_key_bumps() {
    _seam_key_bump(_f1_pos);
    _seam_key_bump(_f2_pos);
    _seam_key_bump(_f3_pos);
}

// A-side form: single natch on +Y.  B mirrors the whole form.
module z_seam_natches_ab() {
    _zseam_natch([0, _zs_y, z_min_scaled]);
}
module z_seam_natches_base() {
    _zseam_natch(_zs1_base_pos);
    _zseam_natch(_zs2_base_pos);
}

module z_seam_key_bumps_ab() {
    _zseam_key_bump([0, _zs_y, z_min_scaled]);
}
module z_seam_key_sockets_base() {
    _zseam_key_socket(_zs1_base_pos);
    _zseam_key_socket(_zs2_base_pos);
}

// --- Final parts ---
// A-side: keys → union sockets; natches → subtract natches.
// B-side: mirror of A, with keys inverted (subtract bumps instead of
// unioning sockets).  Natch case is symmetric.

// Key convention: upper halves (a/b) carry ab-seam sockets or bumps,
// and z-seam bumps subtracted (base part owns the z-seam sockets).

module _b_ab_seam_bumps() {
    _seam_key_bump(_f1_pos);
    _seam_key_bump(_f2_pos);
    _seam_key_bump(_f3_pos);
}

module a_part() {
    if (_use_keys) {
        difference() {
            union() {
                a_part_raw();
                ab_seam_key_sockets();
            }
            if (needs_base) z_seam_key_bumps_ab();
        }
    } else {
        difference() {
            a_part_raw();
            ab_seam_natches();
            if (needs_base) z_seam_natches_ab();
        }
    }
}

module b_part() {
    if (_use_keys) {
        difference() {
            b_part_raw();
            _b_ab_seam_bumps();
            if (needs_base) mirror([0, 1, 0]) z_seam_key_bumps_ab();
        }
    } else {
        difference() {
            b_part_raw();
            ab_seam_natches();
            if (needs_base) mirror([0, 1, 0]) z_seam_natches_ab();
        }
    }
}

// =====================================================================
// BASE PART (rendered only when needs_base)
// =====================================================================
// Open-topped cylindrical cup sitting below A/B at z_min_scaled.  The
// cup has a wt/2 floor and wall_thickness sides; the plaster cavity
// extends from the top of the floor up to the cup's open top (no lid).
// Plaster is poured in separately from above.  The concavity nub and
// mark stamp rise from the inside of the cup's floor, shaping the
// plaster's cast-bottom face — which becomes the plaster piece's
// use-face (the surface that touches the mug's foot) once flipped.

_ab_floor_thickness_ref = wall_thickness / 2;  // mirror of _ab_floor_thickness
_base_total_h = plaster_thickness + _ab_floor_thickness_ref;
_base_z_top = z_min_scaled;
_base_z_bot = _base_z_top - _base_total_h;
_cavity_floor_z = _base_z_bot + _ab_floor_thickness_ref;

// Emit concavity when the path past the inflection contains at least
// one point that rises above z_min — otherwise the "concavity" is a
// flat foot and no nub is needed.
_concavity_rise_eps = 0.01;
_has_real_concavity = len([
    for (i = [body_foot_inflection_idx + 1 : body_foot_idx])
        if (mug_body_profile[i][1] * _cs > z_min_scaled + _concavity_rise_eps) 1
]) > 0;

module base_outer_cylinder() {
    translate([0, 0, _base_z_bot])
        cylinder(h = _base_total_h, r = base_outer_r_derived());
}

// Plaster cavity: open-topped disc carved from the cup interior,
// leaving wt/2 on the bottom and wall_thickness on the sides.
module base_plaster_cavity_disc() {
    translate([0, 0, _cavity_floor_z])
        cylinder(h = _base_z_top - _cavity_floor_z + epsilon,
                 r = base_inner_r_derived());
}

// Foot-concavity profile: points from the foot inflection inward to
// the axis (greenware-scaled).  Drop any trailing points still at
// z_min (the flat foot-ring width) so the axis closure below doesn't
// retrace the ring-edge segment — a zero-area spike at the outer
// vertex would collapse the revolve to a degenerate shape.  The first
// point is retained as the outer ring corner; the closure (0, z_min)
// completes the polygon cleanly along the axis.
_foot_concavity_pts =
    let(
        raw = [for (i = [body_foot_inflection_idx : body_foot_idx])
                 [mug_body_profile[i][0] * _cs,
                  mug_body_profile[i][1] * _cs]],
        first = raw[0],
        rising = [for (i = [1 : len(raw) - 1])
                    if (raw[i][1] > first[1] + _concavity_rise_eps) raw[i]]
    )
    concat([first], rising, [[0, first[1]]]);

_concavity_max_z = max([for (p = _foot_concavity_pts) p[1]]);
_concavity_roof_z = _cavity_floor_z + (_concavity_max_z - z_min_scaled);

// Concavity nub: revolve of the foot-concavity path, rising up from
// the base cavity floor with the mug's foot ring at the bottom and
// the (near-flat) concavity top as its roof.  The roof receives the
// maker's mark.
module base_concavity_positive() {
    if (_has_real_concavity) {
        translate([0, 0, _cavity_floor_z - z_min_scaled])
            rotate_extrude(convexity = 4)
                polygon(points = _foot_concavity_pts);
    }
}

// Maker's mark — stamp polygon positioned against the concavity nub's
// roof.  Built as a stack of progressively offset slices to emulate
// draft: inset (debossed on the mug) tapers inward going up so the
// stamp releases from the plaster dimple; relief (embossed on the mug)
// tapers outward going up so the plaster positive releases the case
// mould.  Matches the mark_stamp implementation in case_mould_original
// and mug.scad.
_mark_depth_scaled = mark_depth * _cs;
_mark_draft = _mark_depth_scaled * tan(mark_draft_angle);
_mark_slices = mark_draft_angle > 0
    ? max(2, round(_mark_depth_scaled / mark_layer_height))
    : 1;

module _mark_stamp_stack() {
    if (mark_draft_angle > 0) {
        _dz = _mark_depth_scaled / _mark_slices;
        for (i = [0 : _mark_slices - 1]) {
            _t = i / (_mark_slices - 1);
            _r = mark_inset
                ? -_mark_draft * _t
                :  _mark_draft * _t;
            translate([0, 0, i * _dz])
                linear_extrude(height = _dz + 0.001, convexity = 4)
                    offset(r = _r, $fn = 0, $fa = mark_fa, $fs = mark_fs)
                        polygon(points = mark_points, paths = mark_paths);
        }
    } else {
        linear_extrude(height = _mark_depth_scaled, convexity = 4)
            polygon(points = mark_points, paths = mark_paths);
    }
}

// mark_inset=true: stamp rises above the roof as a positive; plaster
// forms a dimple around it → flipped, recessed mark on the mug's foot.
// mark_inset=false: stamp is carved into the roof from above; plaster
// fills the recess as a positive → flipped, raised mark on the foot.
module base_mark_stamp() {
    if (mark_enabled && len(mark_points) > 0) {
        _z = mark_inset
            ? _concavity_roof_z - epsilon
            : _concavity_roof_z - _mark_depth_scaled;
        translate([0, 0, _z]) _mark_stamp_stack();
    }
}

// The concavity nub and its mark live inside the plaster cavity region
// and would be erased by the cavity subtraction — add them back after.
module base_raw() {
    union() {
        difference() {
            base_outer_cylinder();
            base_plaster_cavity_disc();
        }
        difference() {
            union() {
                base_concavity_positive();
                if (mark_enabled && mark_inset) base_mark_stamp();
            }
            if (mark_enabled && !mark_inset) base_mark_stamp();
        }
    }
}

// Key convention on Z seam: A/B parts carry bumps rising up from
// their floor inner plane; base carries recessed sockets sinking
// down from its top-floor plane.
module base_part() {
    if (_use_keys) {
        difference() {
            base_raw();
            z_seam_key_sockets_base();
        }
    } else {
        difference() {
            base_raw();
            z_seam_natches_base();
        }
    }
}

// =====================================================================
// PLASTER VOLUME ESTIMATES — always emitted
// =====================================================================
// Low-res VNFs are sufficient for volume estimates.  Axisymmetric plaster
// volume = revolve(plaster_thickness) − revolve(0) − filler_tube_inside_shell.
// Handle plaster = handle_stations_shell_solid − handle_stations_body_positive.
// Base plaster = π·base_inner_r²·plaster_thickness − concavity nub.

_vol_fn = 24;

_vnf_shell_axi = rotate_sweep(offset_profile(plaster_thickness), $fn=_vol_fn);
_vnf_mug_axi   = rotate_sweep(offset_profile(0),                 $fn=_vol_fn);
_v_shell_axi = abs(vnf_volume(_vnf_shell_axi));
_v_mug_axi   = abs(vnf_volume(_vnf_mug_axi));

// Filler tube portion lying inside the axisymmetric shell halo
// (z_lip .. z_lip + plaster_thickness).
_ft_r_bot    = lip_r_scaled;
_ft_h_in     = min(filler_tube_height, plaster_thickness);
_ft_r_top_in = _ft_r_bot + _ft_h_in * tan(filler_tube_angle);
_v_filler_in = (PI * _ft_h_in / 3)
    * (_ft_r_bot*_ft_r_bot + _ft_r_bot*_ft_r_top_in + _ft_r_top_in*_ft_r_top_in);

_vnf_handle_pos = handle_enabled
    ? skin(_hstations_body_pos, slices=0, caps=true)
    : EMPTY_VNF;
_v_handle_pos   = handle_enabled ? abs(vnf_volume(_vnf_handle_pos)) : 0;
// Shell handle is a fat circular tube (path_sweep2d); volume is
// computed analytically in Python and emitted as v_handle_shell_tube.
_v_handle_shell = handle_enabled ? v_handle_shell_tube : 0;

// Correction for the region where the outset handle shell overlaps
// the outset body shell — both are plaster_thickness thick, so the
// intersection near the handle attachment is non-negligible.  The
// Python generator estimates this overlap per-station and emits it
// as v_handle_shell_body_overlap.
_v_plaster_ab_total = (_v_shell_axi - _v_mug_axi - _v_filler_in)
                    + (_v_handle_shell - _v_handle_pos)
                    - v_handle_shell_body_overlap;
_v_ab_half = _v_plaster_ab_total / 2;

_v_concavity = _has_real_concavity
    ? PI * pow(foot_concavity_radius * _cs, 2)
          * (foot_concavity_z * _cs - z_min_scaled)
    : 0;
_v_base_plaster = needs_base
    ? PI * base_inner_r_derived() * base_inner_r_derived() * plaster_thickness - _v_concavity
    : 0;

_v_total_plaster = 2 * _v_ab_half + _v_base_plaster;

echo(str(""));
echo(str("=== PLASTER VOLUME ESTIMATES ==="));
echo(str("  Half A:  ", round(_v_ab_half / 1000), " mL"));
echo(str("  Half B:  ", round(_v_ab_half / 1000), " mL"));
if (needs_base)
    echo(str("  Base:    ", round(_v_base_plaster / 1000), " mL"));
echo(str("  Total:   ", round(_v_total_plaster / 1000), " mL"));
echo(str("================================"));

// =====================================================================
// TOP-LEVEL RENDER
// =====================================================================
// Every render mode sits the part(s) on the Z=0 plane.  In "all" mode
// A and B are nudged apart in Y so their seam walls don't fuse and the
// halves are individually visible.
// "all"  — diagnostic view (A at +Y, B at -Y, base at origin)
// "a"    — A half alone, min Z = 0
// "b"    — B half alone, min Z = 0
// "base" — base alone (only when needs_base), min Z = 0
render_part = "all";

_ab_z_bot = z_min_scaled - _ab_floor_thickness;
_render_split_gap = 20;

module render_all() {
    translate([0,  _render_split_gap, -_ab_z_bot])   a_part();
    translate([0, -_render_split_gap, -_ab_z_bot])   b_part();
    if (needs_base)
        translate([-base_outer_r_derived() * 2 - _render_split_gap * 2, 0, -_base_z_bot]) base_part();
}

if (render_part == "all")       render_all();
else if (render_part == "a")    translate([0, 0, -_ab_z_bot])   a_part();
else if (render_part == "b")    translate([0, 0, -_ab_z_bot])   b_part();
else if (render_part == "base") translate([0, 0, -_base_z_bot]) base_part();
