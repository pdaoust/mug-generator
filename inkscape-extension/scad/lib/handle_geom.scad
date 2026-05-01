// handle_geom.scad — bezpath-based mug body and handle geometry.
//
// Functions in this file consume cubic-Bezier paths (bezpaths) emitted
// directly from the Inkscape extension and produce the polylines and
// stations needed by prototype.scad / case_mould_efficient.scad.
//
// All bezpaths are degree-3 (cubic): a flat list of [x,y] points laid
// out as [knot0, ctrl0a, ctrl0b, knot1, ctrl1a, ctrl1b, knot2, ...].
// A closed path repeats its first knot at the end.
//
// =====================================================================
// BOSL2 cheat sheet (verified against
//   ~/.local/share/OpenSCAD/libraries/BOSL2/beziers.scad as of 2026-04)
// =====================================================================
//
// Single-curve helpers (one cubic, 4 control points):
//   bezier_points(curve, u)              -> point at parameter u (also list/range)
//   bezier_derivative(curve, u, order=1) -> derivative vector at u
//   bezier_tangent(curve, u)             -> unit tangent at u
//   bezier_closest_point(curve, pt, max_err=0.01) -> u
//   bezier_length(curve, start_u=0, end_u=1, max_deflect=0.01) -> arc length
//   bezier_line_intersection(curve, line) -> list of u where curve hits line
//      (line is [p0, p1] of two distinct 2D points; **2D only**)
//
// Bezpath helpers:
//   bezpath_points(bezpath, curveind, u, N=3)  -> point on segment curveind
//   bezpath_curve(bezpath, splinesteps=16, N=3, endpoint=true) -> polyline
//      NOTE: splinesteps is per-segment uniform-u count, NOT $fa/$fs/$fn.
//      bez_to_polyline below derives splinesteps from $fa/$fs/$fn.
//   bezpath_closest_point(bezpath, pt, N=3, max_err=0.01) -> [segnum, u]
//   bezpath_length(bezpath, N=3, max_deflect=0.001) -> total arc length
//   path_to_bezpath(path, closed, tangents, ...) -> fit a bezpath through points
//
// Useful for mug_r_at_z analytic queries:
//   bezier_line_intersection(seg_curve, [[0,z],[1,z]]) gives all u where
//   the segment crosses horizontal line at height z. Evaluate
//   bezier_points(seg_curve, u).x at each u to get all radii at z.

include <BOSL2/std.scad>
include <BOSL2/beziers.scad>


// ---------------------------------------------------------------------
// Phase 1: tessellate a cubic bezpath honoring $fa/$fs/$fn (per-segment).
// ---------------------------------------------------------------------

// Per-segment splinesteps from $fa/$fs/$fn.  Mirrors the resolution
// model of OpenSCAD's primitives: roundup arc-length / $fs and total
// turning / $fa, take the larger.  $fn (when > 0) overrides $fa via
// $fa = 360/$fn (so $fn=64 → 5.625° max angle, similar to a circle).
function _bez_segment_steps(curve, fa, fs, fn) =
    let(
        arclen = bezier_length(curve, max_deflect=0.05)
    )
    (arclen <= 1e-9) ? 1 :
    let(
        // Estimate total turning by sampling derivatives (not unit
        // tangents — unit fails on degenerate sub-intervals where the
        // derivative is zero).  Skip near-zero derivatives.
        samples = 10,
        derivs = [for (i=[0:samples]) bezier_derivative(curve, i/samples)],
        turning_deg = sum([
            for (i=[0:samples-1])
                let(
                    a = derivs[i], b = derivs[i+1],
                    na = norm(a), nb = norm(b)
                )
                (na < 1e-9 || nb < 1e-9) ? 0
                    : acos(constrain((a * b) / (na * nb), -1, 1))
        ]),
        eff_fa = (fn > 0) ? 360/fn : fa,
        n_fa = (eff_fa > 0) ? ceil(turning_deg / eff_fa) : 1,
        n_fs = (fs > 0) ? ceil(arclen / fs) : 1
    )
    max(1, n_fa, n_fs);


// Tessellate a cubic bezpath with $fa/$fs/$fn-aware density.  Each
// segment is sampled independently so curvy parts get more points than
// straight runs.
//
// bez:    cubic bezpath, [k0, c0a, c0b, k1, c1a, c1b, k2, ...].
// closed: if true, the bezpath is interpreted as a closed loop and the
//         final knot (== bez[0]) is omitted from the output (polygon()
//         and friends close automatically).
function _dedupe_consecutive(pts, tol=1e-6) =
    let(n = len(pts))
    (n == 0) ? []
    : concat([pts[0]],
        [for (i = [1:n-1])
            if (norm(pts[i] - pts[i-1]) > tol) pts[i]]);

function bez_to_polyline(bez, closed=false, fa=undef, fs=undef, fn=undef) =
    let(
        _fa = is_undef(fa) ? $fa : fa,
        _fs = is_undef(fs) ? $fs : fs,
        _fn = is_undef(fn) ? $fn : fn,
        N = 3,
        n_segs = floor((len(bez) - 1) / N)
    )
    assert(len(bez) >= N + 1, "bez_to_polyline: bezpath too short")
    let(
        flat = [
            for (i = [0:n_segs-1])
                let(
                    curve = select(bez, i*N, (i+1)*N),
                    steps = _bez_segment_steps(curve, _fa, _fs, _fn)
                )
                each bezier_points(curve, [for (k=[0:steps-1]) k/steps])
        ],
        full = closed ? flat : concat(flat, [last(bez)]),
        deduped = _dedupe_consecutive(full),
        // Closed: also dedupe the wrap-around (last == first).
        nd = len(deduped),
        deduped2 = (closed && nd > 1
                    && norm(deduped[nd-1] - deduped[0]) < 1e-6)
            ? [for (i = [0 : nd - 2]) deduped[i]]
            : deduped
    )
    // Strip near-collinear midpoints so BOSL2's offset() doesn't trip
    // on its near-parallel-segment guard along long shallow runs.
    path_merge_collinear(deduped2, closed=closed, eps=1e-4);

// =====================================================================
// Phase 6: maker's mark — tessellate compound bezpaths and centre.
// =====================================================================
//
// mark_bezpaths is a list of cubic bezpaths (one per subpath) emitted
// from the Inkscape extension.  At render time we tessellate each at
// mark_fa/mark_fs, concatenate into a single points array with index
// paths (so polygon() can render even-odd compound shapes), centre on
// (0,0) by bbox, and apply optional clay-shrinkage scaling.
//
// Returns [centred_points, paths]: feed both into polygon() as
// `polygon(points = ret[0], paths = ret[1])`.

function _cum_starts(sizes, i=0, acc=[0]) =
    i >= len(sizes) ? acc
    : _cum_starts(sizes, i+1, concat(acc, [acc[i] + sizes[i]]));

function mark_tessellate(bezpaths, fa, fs, scale_factor=1) =
    (len(bezpaths) == 0)
        ? [[], []]
        : let(
            polys = [for (b = bezpaths)
                        bez_to_polyline(b, closed=true, fa=fa, fs=fs, fn=0)],
            sizes = [for (p = polys) len(p)],
            starts = _cum_starts(sizes),
            flat = [for (p = polys) each p],
            xs = [for (p = flat) p[0]],
            ys = [for (p = flat) p[1]],
            cx = (min(xs) + max(xs)) / 2,
            cy = (min(ys) + max(ys)) / 2,
            centred = [for (p = flat)
                          [(p[0] - cx) * scale_factor,
                           (p[1] - cy) * scale_factor]],
            paths = [for (i = [0 : len(polys) - 1])
                        [for (k = [0 : sizes[i] - 1]) starts[i] + k]]
        )
        [centred, paths];

// =====================================================================
// Phase 2: analytic body queries
// =====================================================================
//
// All functions here operate directly on cubic bezpaths (N=3) and use
// analytic per-segment evaluation, never just walking knots.  A cubic
// segment can dip below or rise above its endpoint Z values mid-curve,
// so anything that needs an extremum in r or z must look at the
// segment-derivative roots (a quadratic), not just the control points.

// Yield the i-th cubic segment of a bezpath as a 4-control-point list.
function _bez_seg(bez, i, N=3) = select(bez, i*N, i*N + N);

function _n_segs(bez, N=3) = floor((len(bez) - 1) / N);

// Roots in (0,1) of d/du of one coordinate (axis=0 → x/r, axis=1 → y/z).
// The cubic's derivative is a quadratic; this returns its real roots in
// the open interval — endpoint extrema must be added separately.
function _seg_axis_extrema_us(curve, axis) =
    let(
        p0 = curve[0][axis], p1 = curve[1][axis],
        p2 = curve[2][axis], p3 = curve[3][axis],
        a = -p0 + 3*p1 - 3*p2 + p3,
        b = 2*(p0 - 2*p1 + p2),
        c = p1 - p0
    )
    (abs(a) < 1e-14)
        ? ((abs(b) < 1e-14) ? [] :
           let(u = -c/b) (u > 0 && u < 1 ? [u] : []))
        : let(disc = b*b - 4*a*c)
            (disc < 0 ? []
             : let(sq = sqrt(disc),
                   u1 = (-b + sq) / (2*a),
                   u2 = (-b - sq) / (2*a))
               concat(
                   u1 > 0 && u1 < 1 ? [u1] : [],
                   u2 > 0 && u2 < 1 ? [u2] : []
               ));

// All on-curve points where ``axis`` is locally extremal — endpoint
// knots plus per-segment derivative roots.  Used by mug_split_at_rim,
// foot_inflection, and bezpath bbox queries.
function bezpath_extrema_axis(bez, axis) =
    let(
        ns = _n_segs(bez),
        per_seg = [
            for (i = [0:ns-1])
                let(seg = _bez_seg(bez, i),
                    us = _seg_axis_extrema_us(seg, axis))
                each concat(
                    [seg[0]],
                    [for (u = us) bezier_points(seg, u)]
                )
        ]
    )
    concat(per_seg, [last(bez)]);

// Convenience min/max queries — return [r, z] of the extreme point.
function bezpath_min_axis(bez, axis) =
    let(pts = bezpath_extrema_axis(bez, axis))
    pts[search(min([for (p = pts) p[axis]]), [for (p = pts) p[axis]])[0]];

function bezpath_max_axis(bez, axis) =
    let(pts = bezpath_extrema_axis(bez, axis))
    pts[search(max([for (p = pts) p[axis]]), [for (p = pts) p[axis]])[0]];

// Lip point of a closed mug body bezpath, scaled by clay shrinkage cs.
// Drawing convention (outer wall → rim → inner wall → floor) means the
// first max-Z extremum encountered in path order is on the outer side,
// so it has the largest r among any z-tied points.
function lip_pt_scaled(bez, cs) =
    let(p = bezpath_max_axis(bez, 1)) [p[0] * cs, p[1] * cs];

// All on-curve radii where the bezpath crosses height z.  Each segment
// contributes 0–3 crossings (real roots of the per-segment cubic in u
// against y=z); we return the maximum, which corresponds to the outer
// surface for axially-symmetric mug bodies.
//
// Replaces the polyline-walk mug_r_at_z that lived in prototype.scad —
// resolution-independent and aware of mid-curve sweeps.  Named
// mug_r_at_z_bez to keep prototype.scad's single-arg wrapper unambiguous.
function mug_r_at_z_bez(bez, z) =
    let(
        ns = _n_segs(bez),
        rs = [
            for (i = [0:ns-1])
                let(seg = _bez_seg(bez, i),
                    line = [[0, z], [1, z]],
                    us = bezier_line_intersection(seg, line))
                each [for (u = us)
                    if (u >= -1e-9 && u <= 1 + 1e-9)
                        bezier_points(seg, max(0, min(1, u)))[0]
                ]
        ]
    )
    len(rs) == 0 ? undef : max(rs);

// Foot inflection on the *outer half* bezpath: the on-curve point with
// minimum z (analytic — searches segment-derivative roots, not just
// knots).  Returns [r, z].  Only meaningful on a bezpath that has
// already been split at the rim (prototype.scad, case_mould_*.scad use the
// closed body and call mug_foot_idx instead).
function foot_inflection(outer_bez) = bezpath_min_axis(outer_bez, 1);

// Inflections in z along the bezpath — knots and mid-curve extrema.
// Returns [[r0, z0], [r1, z1], ...] sorted by z ascending.  Drives the
// rim/foot/concavity decisions when the closed body is not yet split.
function bezpath_inflections_y_axis(bez) =
    let(pts = bezpath_extrema_axis(bez, 1))
    sort(pts, idx=1);

// Rim-aligned, scaled mug-body polyline.  Replaces the
// align_polyline_to(bez_to_polyline(...)) + scale dance that used to
// live at the top of every mould .scad file.  Direction is resolved
// analytically: rotate to start at the rim (max-z knot), then walk
// toward the larger-r neighbour so the outer wall comes first.
function mug_body_polyline(bez, scale_factor=1, fa=undef, fs=undef, fn=undef) =
    let(
        raw = bez_to_polyline(bez, closed=true, fa=fa, fs=fs, fn=fn),
        rim = bezpath_max_axis(bez, 1),
        rim_idx = nearest_polyline_idx(raw, [rim[0], rim[1]]),
        n = len(raw),
        prev_r = raw[(rim_idx - 1 + n) % n][0],
        next_r = raw[(rim_idx + 1) % n][0],
        rotated = [for (i = [0:n-1]) raw[(rim_idx + i) % n]],
        oriented = (next_r >= prev_r)
            ? rotated
            : concat([rotated[0]], [for (i = [n-1 : -1 : 1]) rotated[i]])
    )
    [for (p = oriented) [p[0] * scale_factor, p[1] * scale_factor]];

// Polyline index of the foot centre — the first point (walking from
// the rim, index 0) where the trace returns to the axis (r ≈ 0).  This
// is the natural split between the outer and inner halves of the
// closed body cross-section.  The closed body of a mug with a concave
// foot ring crosses the axis twice (foot-concavity peak, then cup-
// interior bottom); we want the first crossing so the outer slice
// includes the full foot-ring/concavity walk and the inner slice is
// just the cup interior.  Falls back to the global min-r point when
// the polyline never reaches the axis.  ``scale_factor`` matches the
// scale applied by ``mug_body_polyline`` so the threshold stays in
// the polyline's units.  ``bez`` is unused (kept for call-site
// compatibility with the bezpath-aware variants nearby).
function mug_foot_idx(polyline, bez, scale_factor=1) =
    let(
        AXIS_THRESHOLD = 0.1 * scale_factor,
        n = len(polyline),
        first_axis = [for (i = [0:n-1])
            if (polyline[i][0] < AXIS_THRESHOLD) i]
    )
    (len(first_axis) > 0)
        ? first_axis[0]
        : let(
            rs = [for (p = polyline) p[0]],
            min_r = min(rs)
          )
          [for (i = [0:n-1]) if (rs[i] == min_r) i][0];

// Polyline index of the foot inflection point (start of the concave
// foot ring, when present).  Walks the rim-first polyline from rim
// (index 0) to the foot centre and returns the index with the lowest
// z, breaking ties on the largest r — matches the legacy Python
// computation that drove ``body_foot_inflection_idx``.
function mug_foot_inflection_idx(polyline, foot_idx) =
    let(
        keys = [for (i = [0:foot_idx])
                    [-polyline[i][1], polyline[i][0], i]],
        max_negz = max([for (k = keys) k[0]]),
        tied = [for (k = keys) if (k[0] == max_negz) k],
        max_r = max([for (k = tied) k[1]]),
        winner = [for (k = tied) if (k[1] == max_r) k][0]
    )
    winner[2];

// =====================================================================
// Phase 3: rails, midline, stations
// =====================================================================
//
// Stations are flat 7-tuples kept as a list of vectors so they survive
// OpenSCAD's value semantics:
//   [centroid_x, centroid_y, centroid_z,
//    x_axis,  // [3]
//    y_axis,  // [3]
//    z_axis,  // [3]
//    sx,      // inner-outer width (scalar)
//    sz,      // tangential width from side rails (scalar)
//    arc_frac // [0,1] along midpoint curve
//   ]
// In SCAD we just access by index.

function station(c, xa, ya, za, sx, sz, frac) = [c, xa, ya, za, sx, sz, frac];
function st_c(s)  = s[0];
function st_xa(s) = s[1];
function st_ya(s) = s[2];
function st_za(s) = s[3];
function st_sx(s) = s[4];
function st_sz(s) = s[5];
function st_f(s)  = s[6];

// 2D arc-length sample on a bezpath.  Returns [point_2d, unit_tangent_2d].
// Uses BOSL2 bezpath_length to total the bezpath, then walks segments
// keeping running arc-length to find the segment that owns a given
// fraction.  Mid-segment u is found by Newton-stepping the segment's
// arc-length integral, but since Bezier arc length doesn't have a
// closed form we approximate with binary search on bezier_length over
// [0, u].
function _bez_total_length(bez, N=3) =
    bezpath_length(bez, N=N, max_deflect=0.01);

// Find u in [0,1] on a single cubic where the arc length from 0 to u
// equals target.  Binary search; converges fast for short segments.
function _u_at_arclen_in_segment(curve, target, lo=0, hi=1, depth=0) =
    (depth >= 20) ? (lo + hi) / 2
    : let(mid = (lo + hi) / 2,
          len = bezier_length(curve, start_u=0, end_u=mid, max_deflect=0.005))
        (abs(len - target) < 1e-4) ? mid
        : (len < target) ? _u_at_arclen_in_segment(curve, target, mid, hi, depth+1)
        : _u_at_arclen_in_segment(curve, target, lo, mid, depth+1);

// Sample a bezpath at arc-length fraction frac in [0,1].
// Returns [point, unit_tangent].  Uses cumulative segment lengths.
function _bezpath_at_frac(bez, frac, seg_lens=undef) =
    let(
        ns = _n_segs(bez),
        lens = is_undef(seg_lens)
            ? [for (i = [0:ns-1]) bezier_length(_bez_seg(bez, i), max_deflect=0.01)]
            : seg_lens,
        total = sum(lens),
        target = frac * total
    )
    _walk_segments_to(bez, lens, ns, target, 0, 0);

// Walk forward through segment cumulative lengths to find which segment
// contains `target` arc length, then locate u within that segment.
function _walk_segments_to(bez, lens, ns, target, idx, accum) =
    (idx >= ns - 1 || accum + lens[idx] >= target)
        ? let(
            seg = _bez_seg(bez, idx),
            local_target = max(0, target - accum),
            u = (lens[idx] < 1e-9) ? 0
                : _u_at_arclen_in_segment(seg, local_target),
            pt = bezier_points(seg, u),
            d = bezier_derivative(seg, u),
            nd = norm(d),
            tan = (nd < 1e-9) ? [1, 0] : d / nd
          )
          [pt, tan]
        : _walk_segments_to(bez, lens, ns, target, idx + 1, accum + lens[idx]);

// Build the midpoint curve between two rail bezpaths.  Sample both at
// matching arc-length fractions and average.  Returns a polyline.
function build_midpoint_curve_bez(inner_bez, outer_bez, n_dense=200) =
    let(
        in_lens  = [for (i = [0:_n_segs(inner_bez)-1])
                        bezier_length(_bez_seg(inner_bez, i), max_deflect=0.01)],
        out_lens = [for (i = [0:_n_segs(outer_bez)-1])
                        bezier_length(_bez_seg(outer_bez, i), max_deflect=0.01)]
    )
    [for (i = [0:n_dense])
        let(t = i / n_dense,
            p_in  = _bezpath_at_frac(inner_bez,  t, in_lens)[0],
            p_out = _bezpath_at_frac(outer_bez, t, out_lens)[0])
        (p_in + p_out) / 2
    ];

// Sample inner/outer rail bezpaths at n_stations evenly-spaced arc
// fractions and build station frames.  Mirrors rail_sampler.sample_rails:
// frames are in 3D with Y=0 (the SVG drawing plane); analytic tangents
// from the bezpath replace the polyline finite-difference tangents.
function sample_rails_bez(inner_bez, outer_bez, n_stations) =
    let(
        in_lens  = [for (i = [0:_n_segs(inner_bez)-1])
                        bezier_length(_bez_seg(inner_bez, i), max_deflect=0.01)],
        out_lens = [for (i = [0:_n_segs(outer_bez)-1])
                        bezier_length(_bez_seg(outer_bez, i), max_deflect=0.01)],
        raw = [for (i = [0:n_stations-1])
            let(
                frac  = i / (n_stations - 1),
                ip = _bezpath_at_frac(inner_bez,  frac, in_lens),
                op = _bezpath_at_frac(outer_bez, frac, out_lens),
                p_in = ip[0],   t_in = ip[1],
                p_out = op[0],  t_out = op[1],
                cx = (p_in[0] + p_out[0]) / 2,
                cz = (p_in[1] + p_out[1]) / 2,
                centroid = [cx, 0, cz],
                dx = p_out[0] - p_in[0],
                dz = p_out[1] - p_in[1],
                sx = norm([dx, dz]),
                x_axis = (sx < 1e-12) ? [1, 0, 0] : [dx/sx, 0, dz/sx],
                fwd = [(t_in[0] + t_out[0]) / 2, 0, (t_in[1] + t_out[1]) / 2],
                proj = fwd * x_axis,
                fwd_orth = fwd - proj * x_axis,
                fwd_len = norm(fwd_orth),
                y_axis = (fwd_len < 0.5) ? [0, 0, 1] : fwd_orth / fwd_len,
                z_axis_raw = cross(x_axis, y_axis),
                z_axis = z_axis_raw / norm(z_axis_raw)
            )
            station(centroid, x_axis, y_axis, z_axis, sx, 0, frac)
        ]
    )
    _flip_fix_z_axes(raw, 1);

// Walk stations and flip z_axis when it dot-product-flips against the
// previous one — handle bends can flip x_axis, which would flip z and
// twist the loft.
function _flip_fix_z_axes(stations, i) =
    (i >= len(stations)) ? stations
    : let(
        prev = st_za(stations[i-1]),
        cur  = st_za(stations[i]),
        flip = (prev * cur) < 0,
        fixed = flip
            ? [for (j = [0:len(stations)-1])
                (j == i)
                    ? station(st_c(stations[j]), st_xa(stations[j]),
                              st_ya(stations[j]), -st_za(stations[j]),
                              st_sx(stations[j]), st_sz(stations[j]), st_f(stations[j]))
                    : stations[j]]
            : stations
      )
      _flip_fix_z_axes(fixed, i + 1);

// Side rails: two polylines (or bezpaths flattened to polylines) where
// X = half-width and Y = position along the handle.  Y values from
// both rails are normalized together to [0,1] mapping start→end of the
// handle, then per-station fractions look up width on each rail.
//
// Takes already-tessellated polylines for simplicity (the side rails
// are typically straight or near-straight, so $fa/$fs tessellation
// from Python or a single bez_to_polyline call is fine).
function apply_side_rails(stations, left_rail, right_rail) =
    let(
        all_ys = concat([for (p = left_rail) p[1]], [for (p = right_rail) p[1]]),
        y_min = min(all_ys),
        y_max = max(all_ys),
        y_range = y_max - y_min,
        norm_y = function (y) (y_range < 1e-12) ? 0.5 : (y - y_min) / y_range,
        l_sorted = sort(left_rail,  idx=1),
        r_sorted = sort(right_rail, idx=1),
        l_fracs  = [for (p = l_sorted) norm_y(p[1])],
        l_widths = [for (p = l_sorted) p[0]],
        r_fracs  = [for (p = r_sorted) norm_y(p[1])],
        r_widths = [for (p = r_sorted) p[0]]
    )
    [for (s = stations)
        let(
            f = st_f(s),
            lw = _interp_1d(l_fracs, l_widths, f),
            rw = _interp_1d(r_fracs, r_widths, f),
            half = (abs(lw) + abs(rw)) / 2
        )
        station(st_c(s), st_xa(s), st_ya(s), st_za(s),
                st_sx(s), 2.0 * half, st_f(s))
    ];

// 1D linear interpolation/extrapolation on sorted (xs, ys) pairs.
function _interp_1d(xs, ys, x) =
    let(n = len(xs))
    (n == 0) ? 0
    : (n == 1) ? ys[0]
    : (x <= xs[0])
        ? let(dx = xs[1] - xs[0])
            (abs(dx) < 1e-12) ? ys[0]
            : ys[0] + (ys[1] - ys[0]) / dx * (x - xs[0])
    : (x >= xs[n-1])
        ? let(dx = xs[n-1] - xs[n-2])
            (abs(dx) < 1e-12) ? ys[n-1]
            : ys[n-1] + (ys[n-1] - ys[n-2]) / dx * (x - xs[n-1])
    : _interp_1d_walk(xs, ys, x, 1);

function _interp_1d_walk(xs, ys, x, i) =
    (xs[i] >= x)
        ? let(dx = xs[i] - xs[i-1])
            (abs(dx) < 1e-12) ? ys[i]
            : ys[i-1] + (x - xs[i-1]) / dx * (ys[i] - ys[i-1])
        : _interp_1d_walk(xs, ys, x, i + 1);

// Shoelace area for a 2D polygon — positive = CCW.
function _shoelace_area(pts) =
    let(n = len(pts),
        s = sum([for (i = [0:n-1])
            let(j = (i + 1) % n)
            pts[i][0] * pts[j][1] - pts[j][0] * pts[i][1]
        ]))
    s / 2;

// Normalize a 2D profile polygon: bbox-center to origin, scale each
// axis to [-0.5, 0.5], enforce CCW winding.
function normalize_profile(profile) =
    let(
        xs = [for (p = profile) p[0]],
        ys = [for (p = profile) p[1]],
        x0 = min(xs), x1 = max(xs),
        y0 = min(ys), y1 = max(ys),
        w = x1 - x0,
        h = y1 - y0,
        cx = (x0 + x1) / 2,
        cy = (y0 + y1) / 2
    )
    assert(w >= 1e-12 && h >= 1e-12, "normalize_profile: zero extent")
    let(norm = [for (p = profile) [(p[0] - cx) / w, (p[1] - cy) / h]])
    (_shoelace_area(norm) < 0) ? reverse(norm) : norm;

// Transform a normalized 2D profile into a 3D station polygon (flat
// frame, no cylinder wrapping).
function transform_profile_at_station(profile, s) =
    [for (uv = profile)
        let(su = uv[0] * st_sz(s),
            sv = uv[1] * st_sx(s))
        st_c(s) + sv * st_xa(s) + su * st_za(s)
    ];

// Cylinder-wrapped variant: blend width direction from station z_axis
// toward the mug-cylinder tangent at this station's centroid.  Adds a
// sagitta correction so the wrapped strip lies on the cylinder
// surface, not its tangent plane.
function transform_profile_blended(profile, s, axis_x, mug_r, blend) =
    let(
        c = st_c(s),
        to_a = [axis_x - c[0], -c[1]],
        to_len = norm(to_a),
        inward = (to_len > 1e-9) ? to_a / to_len : [0, 0],
        tan_xy_raw = [-inward[1], inward[0]],
        za = st_za(s),
        z_dot = za[0] * tan_xy_raw[0] + za[1] * tan_xy_raw[1],
        tan_xy = (z_dot < 0) ? [inward[1], -inward[0]] : tan_xy_raw,
        tangent = [tan_xy[0], tan_xy[1], 0]
    )
    [for (uv = profile)
        let(
            su = uv[0] * st_sz(s),
            sv = uv[1] * st_sx(s),
            wd_raw = (1 - blend) * za + blend * tangent,
            wd_len = norm(wd_raw),
            wd = (wd_len > 1e-12) ? wd_raw / wd_len : za,
            base = c + sv * st_xa(s) + su * wd,
            su_tan = su * (wd[0] * tangent[0] + wd[1] * tangent[1]),
            sagitta = (to_len > 1e-9) ? to_len * (1 - cos_rad(su_tan / to_len)) : 0
        )
        base + sagitta * [inward[0], inward[1], 0]
    ];

// OpenSCAD's cos() takes degrees; convert from radians.
function cos_rad(r) = cos(r * 180 / PI);

// Generate all handle cross-section polygons for skin().  Wraps the
// profile onto the mug cylinder near the endpoints (blend goes 0→1
// from frac=0.5 outward) when axis_x is non-undef and a body bezpath
// is supplied for radius queries.
function generate_handle_stations_bez(profile_polyline, stations,
                                       axis_x=undef, body_bez=undef) =
    let(
        norm = normalize_profile(profile_polyline),
        can_wrap = !is_undef(axis_x) && !is_undef(body_bez)
    )
    [for (s = stations)
        can_wrap
            ? let(mug_r = mug_r_at_z_bez(body_bez, st_c(s)[2]))
                (is_undef(mug_r) || mug_r <= 0)
                    ? transform_profile_at_station(norm, s)
                    : transform_profile_blended(
                        norm, s, axis_x, mug_r,
                        2.0 * abs(st_f(s) - 0.5))
            : transform_profile_at_station(norm, s)
    ];

// =====================================================================
// Phase 4: nudge handle endpoints onto the mug surface
// =====================================================================
//
// Hypar-weighted radial nudge: at each endpoint, the radial excess is
// measured at the side-rail midline (|v| < 0.1 in the normalized
// profile, i.e. the points sticking out furthest toward ±Y).  That
// excess is propagated inward along the handle with a piecewise-linear
// blend that decays to zero at the midpoint, and along each cross-
// section with a (1 - 4v²) hypar so the inner/outer rail vertices
// (v = ±0.5) stay anchored on the artist's path.
//
// Compared to the Python original, mug_r_at_z(body_bez, z) is the
// analytic per-segment cubic root finder — no polyline walk, no
// resolution coupling.

// Average radial excess at the side-rail midline for one station.
// ``target_offset`` shifts the comparison surface inward (negative) or
// outward (positive) relative to the bare body radius — used by the
// inner-wall handle so its endcaps get nudged onto the inset surface
// rather than the bare one.
function _side_rail_excess_bez(station_pts, norm_profile, body_bez, axis_x,
                                target_offset = 0) =
    let(
        n = len(norm_profile),
        // |v| sorted ascending — the smallest |v| are the side-rail
        // midline points.
        candidates = sort([for (j = [0:n-1]) [abs(norm_profile[j][1]), j]],
                          idx=0),
        threshold = 0.1,
        below = [for (c = candidates) if (c[0] < threshold) c[1]],
        selected = (len(below) > 0) ? below : [candidates[0][1]],
        excesses = [for (j = selected)
            let(
                pt = station_pts[j],
                dx = pt[0] - axis_x,
                dy = pt[1],
                r = norm([dx, dy]),
                R = mug_r_at_z_bez(body_bez, pt[2])
            )
            r - (is_undef(R) ? r : R + target_offset)
        ]
    )
    sum(excesses) / len(excesses);

function nudge_handle_stations_bez(stations_3d, station_frames,
                                    norm_profile, body_bez, axis_x,
                                    target_offset = 0) =
    let(
        n = len(stations_3d)
    )
    (n < 3) ? stations_3d
    : let(
        top_excess = _side_rail_excess_bez(
            stations_3d[0], norm_profile, body_bez, axis_x, target_offset),
        bot_excess = _side_rail_excess_bez(
            stations_3d[n-1], norm_profile, body_bez, axis_x, target_offset),
        hypar = [for (uv = norm_profile) 1 - 4 * uv[1] * uv[1]]
    )
    [for (i = [0:n-1])
        let(
            frac = i / (n - 1),
            blend_top = max(0, 1 - 2 * frac),
            blend_bot = max(0, 2 * frac - 1),
            excess = blend_top * top_excess + blend_bot * bot_excess,
            c = st_c(station_frames[i]),
            cdx = c[0] - axis_x,
            cdy = c[1],
            cr = norm([cdx, cdy])
        )
        (abs(excess) < 1e-6 || cr < 0.001 ||
         (blend_top < 1e-6 && blend_bot < 1e-6))
            ? stations_3d[i]
            : let(
                rad_x = cdx / cr,
                rad_y = cdy / cr
            )
            [for (j = [0:len(stations_3d[i])-1])
                let(
                    pt = stations_3d[i][j],
                    correction = excess * hypar[j]
                )
                (abs(correction) < 1e-6) ? pt
                    : [pt[0] - correction * rad_x,
                       pt[1] - correction * rad_y,
                       pt[2]]
            ]
    ];

// =====================================================================
// Phase 5: mould variants
// =====================================================================
//
// case_mould_efficient.scad needs four sweep variants (positive,
// inner-wall, shell-solid, shell-outer); each is the same lofted skin
// scaled radially by 2*d on the cross-section axes (sx, sz).  The two
// shell variants additionally use a coarser tessellation of the same
// bezpaths (lower n_stations and coarser handle profile) since they
// live inside plaster.
//
// Functions here are pure transforms over the station 7-tuple; the
// per-call-site $fa/$fs/$fn dial is applied at bez_to_polyline /
// sample_rails_bez time, not here.

// Scale every station's sx/sz by 2*d.  Centroids and frames stay put.
function offset_stations(stations, d) =
    [for (s = stations)
        station(st_c(s), st_xa(s), st_ya(s), st_za(s),
                max(0.001, st_sx(s) + 2.0 * d),
                max(0.001, st_sz(s) + 2.0 * d),
                st_f(s))];

// Prepend/append one station at each end, stepped along the
// neighbour-to-endpoint vector by ``distance``.  Frame, sx/sz, frac
// inherit from the endpoint (frac stays at 0 or 1).
function _step_centroid(a, b, dist) =
    let(d = b - a, len = norm(d))
    (len < 1e-12) ? b : b + d * (dist / len);

function extend_station_endpoints(stations, distance) =
    (len(stations) < 2 || distance <= 0) ? stations
    : let(
        n = len(stations),
        c0 = _step_centroid(st_c(stations[1]),   st_c(stations[0]),   distance),
        cN = _step_centroid(st_c(stations[n-2]), st_c(stations[n-1]), distance),
        s0 = stations[0],
        sN = stations[n-1],
        new0 = station(c0, st_xa(s0), st_ya(s0), st_za(s0),
                        st_sx(s0), st_sz(s0), st_f(s0)),
        newN = station(cN, st_xa(sN), st_ya(sN), st_za(sN),
                        st_sx(sN), st_sz(sN), st_f(sN))
    )
    concat([new0], stations, [newN]);

// Newell-sum area of a planar polygon in 3D (handles closed or open
// inputs; duplicate endpoints contribute zero-area triangles).
function _newell_area(pts) =
    (len(pts) < 3) ? 0
    : let(
        p0 = pts[0],
        sums = [for (i = [1 : len(pts) - 2])
            let(a = pts[i] - p0, b = pts[i+1] - p0)
            cross(a, b)
        ],
        nx = sum([for (s = sums) s[0]]),
        ny = sum([for (s = sums) s[1]]),
        nz = sum([for (s = sums) s[2]])
    )
    0.5 * norm([nx, ny, nz]);

function _poly_centroid3(pts) =
    let(
        p = (len(pts) > 1 && pts[0] == pts[len(pts)-1])
            ? [for (i = [0 : len(pts) - 2]) pts[i]]
            : pts,
        n = len(p)
    )
    (n == 0) ? [0, 0, 0]
    : [sum([for (q = p) q[0]]) / n,
       sum([for (q = p) q[1]]) / n,
       sum([for (q = p) q[2]]) / n];

// Approximate the volume where the outset handle shell overlaps the
// outset body shell.  Per station: area · spacing · radial fraction
// inside the band [mug_r(z), mug_r(z) + plaster_thickness], using
// analytic mug_r_at_z_bez.  See lib/handle_shell_overlap.py for the
// derivation and assumptions.
function handle_shell_body_overlap_volume(shell_stations, body_bez,
                                           plaster_thickness) =
    let(n = len(shell_stations))
    (n < 2) ? 0
    : let(
        cents = [for (s = shell_stations) _poly_centroid3(s)],
        seg = [for (i = [0 : n - 2]) norm(cents[i+1] - cents[i])],
        spacing = [for (i = [0 : n - 1])
            (i == 0)     ? seg[0] * 0.5
            : (i == n-1) ? seg[n-2] * 0.5
            :              (seg[i-1] + seg[i]) * 0.5
        ],
        contribs = [for (i = [0 : n - 1])
            let(
                station_pts = shell_stations[i],
                radii = [for (p = station_pts) norm([p[0], p[1]])],
                r_min = min(radii),
                r_max = max(radii),
                z = cents[i][2],
                mug_r = mug_r_at_z_bez(body_bez, z),
                band_lo = is_undef(mug_r) ? undef : mug_r,
                band_hi = is_undef(mug_r) ? undef : mug_r + plaster_thickness,
                ov_lo = is_undef(band_lo) ? 0 : max(r_min, band_lo),
                ov_hi = is_undef(band_hi) ? 0 : min(r_max, band_hi)
            )
            (is_undef(mug_r) || r_max <= r_min || ov_hi <= ov_lo) ? 0
            : _newell_area(station_pts) * spacing[i]
              * (ov_hi - ov_lo) / (r_max - r_min)
        ]
    )
    sum(contribs);

// =====================================================================
// Polyline / bezpath index helpers
// =====================================================================
//
// Used by mould files (case_mould_efficient, slump_mould, hump_mould,
// case_mould_original, funnel, *_rib) to map a legacy
// polyline index — emitted by Python from the original sampled
// polyline — into the equivalent index in a freshly-tessellated
// bezpath polyline whose density depends on $fa/$fs.

// Rotate a closed polyline so it begins at the index nearest to target.
function rotate_polyline_to(pts, target) =
    let(
        idx = nearest_polyline_idx(pts, target),
        n = len(pts)
    )
    [for (i = [0:n-1]) pts[(idx + i) % n]];

// Rotate AND orient a closed polyline: starts at target0, with the next
// point closer to target1 than to the wrap-around-end.  Reverses direction
// if needed.
function align_polyline_to(pts, target0, target1) =
    let(
        rotated = rotate_polyline_to(pts, target0),
        n = len(rotated),
        d_fwd = norm([rotated[1][0]-target1[0], rotated[1][1]-target1[1]]),
        d_rev = norm([rotated[n-1][0]-target1[0], rotated[n-1][1]-target1[1]])
    )
    d_fwd <= d_rev
        ? rotated
        : concat([rotated[0]], [for (i=[n-1:-1:1]) rotated[i]]);

function nearest_polyline_idx(pts, target) =
    let(
        dists = [for (i = [0 : len(pts)-1])
                    norm([pts[i][0] - target[0], pts[i][1] - target[1]])],
        min_d = min(dists),
        idx = [for (i = [0 : len(pts)-1]) if (dists[i] == min_d) i][0]
    )
    idx;

function nearest_bez_knot(bez, target_xz, N=3) =
    let(
        n_knots = floor(len(bez) / N),
        dists = [for (k = [0:n_knots-1])
                    norm([bez[k*N][0] - target_xz[0],
                          bez[k*N][1] - target_xz[1]])],
        min_d = min(dists),
        idx = [for (k = [0:n_knots-1]) if (dists[k] == min_d) k][0]
    )
    idx;

// Sub-bezpath from knot_a → knot_b.  If knot_a > knot_b, walk the
// bezpath backwards: each reversed segment swaps its two control points
// so the curve geometry is preserved while traversal direction flips.
function bez_subpath(bez, knot_a, knot_b, N=3) =
    knot_a <= knot_b
        ? [for (i = [knot_a*N : knot_b*N]) bez[i]]
        : concat(
            [bez[knot_a * N]],
            [for (k = [knot_a - 1 : -1 : knot_b])
                each [bez[k*N + 2], bez[k*N + 1], bez[k*N]]]);
