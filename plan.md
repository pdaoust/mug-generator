# Mug Generator: Inkscape Extension + OpenSCAD Pipeline
## Implementation Plan for Claude Code

---

## Project overview

An Inkscape 1.x extension that reads artistic guide geometry from named SVG layers,
computes a four-rail lofted handle and revolved mug body, and emits a set of generated
`.scad` data files plus a static `mug.scad` assembly file into a user-specified output
directory. The static assembly file is copied from the extension's own `scad/` directory
unchanged.

Future mould generation (block moulds, case moulds) will reuse the same data files with
different static assembly files — the architecture anticipates this from the start.

---

## Repository structure

```
mug-generator/
  inkscape-extension/
    mug_generator.inx          # Inkscape extension manifest
    mug_generator.py           # Extension entry point
    lib/
      svg_layers.py            # Layer discovery and path extraction
      units.py                 # SVG unit/px conversion
      rail_sampler.py          # Four-rail sampling and frame computation
      profile_transformer.py   # Per-station profile generation
      side_rail_extender.py    # Side rail tapering to mug surface
      mug_surface.py           # Mug body surface query (radius at z)
      scad_writer.py           # .scad file emission (registry pattern)
      preview.py               # Inkscape preview overlay (temporary SVG elements)
      openscad_params.py       # $fn/$fa/$fs smoothness logic
  scad/
    mug.scad                   # Static assembly file (hand-written, copied to output)
    moulds/                    # Future: block_mould.scad, case_mould.scad, etc.
  tests/
    test_rail_sampler.py
    test_profile_transformer.py
    test_side_rail_extender.py
    test_mug_surface.py
    test_units.py
    fixtures/
      sample.svg
      expected/                # Expected .scad output for integration test
  docs/
    layer-conventions.md
    scad-data-format.md
```

---

## Layer conventions

The extension identifies layers by label (case-insensitive, whitespace-tolerant).

| Layer label      | Contents | Coordinate space |
|------------------|----------|------------------|
| `mug body`       | Single open path: right-hand half-profile, drawn top to bottom | Shared world space |
| `handle rails`   | Exactly two paths: inner rail and outer rail, both drawn top to bottom | Shared world space |
| `side rails`     | Exactly two paths: left side and right side | Arbitrary SVG coords; Y mapped to arc-length fraction, X is absolute half-width in document units |
| `handle profile` | Single closed path: lenticular or arbitrary cross-section | Arbitrary; normalized to unit bounding box internally |

Layer discovery must be tolerant of missing layers and emit clear error messages naming
the missing layer. Wrong path counts (e.g. three paths in `handle rails`) should also
abort with a clear message.

---

## Unit handling (`units.py`)

- Read `viewBox` and `width`/`height` attributes from the SVG root element
- Determine document units from the `width` attribute suffix: mm, cm, in, px, pt, pc
- If units are px, apply the standard 96 px = 25.4 mm conversion
- Expose a single `to_mm(value, doc_units) -> float` function used everywhere else
- All coordinates passed to `scad_writer.py` are in mm

---

## Path extraction (`svg_layers.py`)

- Use the `inkex` API to walk the layer's children and find path elements
- For each path, use `inkex.Path.to_superpath()` then dense cubic Bézier sampling
  to convert to a polyline of `[x, y]` points in document units
- Apply the element's transform and all ancestor transforms before extracting points
- Return raw point lists; unit conversion happens in the caller
- Expose `get_layer_paths(svg, label) -> list[list[[x,y]]]`

---

## Rail sampler (`rail_sampler.py`)

This is the geometric heart of the extension.

### Arc-length parameterisation

- For each of the four rails, compute cumulative chord length and normalize to [0, 1]
- Resample each rail to N evenly-spaced arc-length stations using linear interpolation
  between the dense sample points
- N is determined by the OpenSCAD smoothness parameters (see `openscad_params.py`)

### Per-station frame computation

At each station i, given inner rail point `P_in[i]` and outer rail point `P_out[i]`:

1. **Centroid**: `C[i] = (P_in[i] + P_out[i]) / 2`
2. **Tilt axis (X)**: `X[i] = normalize(P_out[i] - P_in[i])`
3. **Scale X**: `sx[i] = length(P_out[i] - P_in[i])`
4. **Forward axis (Y)**: average of the tangents of all four rails at station i,
   orthogonalised against X[i] via Gram-Schmidt
5. **Normal axis (Z)**: `Z[i] = cross(X[i], Y[i])`
6. **Scale Z**: `sz[i]` — from side rails (see Side rail mapping below)

### Side rail mapping

The side rails are drawn in an abstract SVG space where:
- Y coordinates are arbitrary SVG values; they are normalised so that
  `min(Y) → 0` and `max(Y) → 1`, then mapped to arc-length fraction along
  the inner/outer rails
- X coordinates are the profile half-width in document units (converted to mm)

At each station i, interpolate the side rail's X value at the corresponding
arc-length fraction to obtain `sz[i]`.

**Important**: the artist is responsible for placing the inner/outer rail endpoints
on (or very slightly into) the mug body surface. The side rails, however, must taper
to zero width exactly at the mug surface — see `side_rail_extender.py` below.

### Output

A list of N frames, each a dataclass or namedtuple containing:
- `position`: 3-vector (mm)
- `orientation`: 3×3 matrix (columns are X, Y, Z axes)
- `scale`: 2-vector `(sx, sz)` in mm

---

## Side rail extender (`side_rail_extender.py`)

This module handles the end-cap geometry so that the loft terminates as a saddle
edge flush with the mug body rather than a flat face.

### Problem

The side rails define profile width along the arc-length fraction [0, 1] of the
inner/outer rails. But the loft must taper to zero width exactly at the mug surface.
If the inner/outer rail endpoints are on the mug surface, the side rails' Y=0 and Y=1
values will have some finite width — producing a flat endcap. To get a saddle, the
width must reach zero exactly at the mug surface.

### Solution

At each end of the handle:

1. Query `mug_surface.py` to find the radius of the mug body at the z-coordinate of
   the inner/outer rail endpoint
2. Determine the distance along the inner/outer rail from the endpoint back to where
   the rail crosses the mug surface (should be near zero if the artist placed endpoints
   correctly, but computable nonetheless)
3. Extrapolate the side rail's width curve linearly beyond Y=0 (or Y=1) to find where
   it would reach zero width
4. Add one extra station beyond the artist's endpoint at the zero-width position,
   coincident with the mug surface

This gives the loft a natural tapered termination that mates cleanly with the mug body.
The boolean union in OpenSCAD then handles any tiny residual gap or overlap.

### Validation

Warn (but do not abort) if:
- The zero-width extrapolation distance is very large (side rail doesn't taper toward zero)
- The inner/outer rail endpoint is far from the mug surface (artist may have misplaced it)

Abort with a clear message if:
- The side rail's width is increasing toward the endpoint (would never reach zero)

---

## Mug surface query (`mug_surface.py`)

A lightweight module that represents the revolved mug body surface for geometric queries.

- Takes the mug half-profile polyline (list of `[x, z]` points in mm, x = radius, z = height)
- Exposes `radius_at_z(z) -> float`: interpolates the profile to return the mug radius
  at a given height. Returns None if z is outside the profile's range.
- Exposes `surface_point_at(y_offset, z) -> [x, y, z]`: given a position in the
  shared 2D coordinate space, returns the corresponding 3D point on the mug surface

Used by `side_rail_extender.py` to compute the zero-width terminal stations.

---

## Profile transformer (`profile_transformer.py`)

- Normalise the handle profile path to a unit bounding box centered at the origin
- At each station i, apply:
  1. Scale by `(sx[i], sz[i])`
  2. Rotate by the orientation matrix `(X[i], Y[i], Z[i])`
  3. Translate to `position[i]`
- Output: list of N closed polygons, each a list of `[x, y, z]` points in mm
- These become the per-station profile list passed to BOSL2's `skin()`

---

## OpenSCAD smoothness parameters (`openscad_params.py`)

Replicates OpenSCAD's logic for determining N from `$fn`, `$fa`, `$fs`:

- If `$fn > 0`: N = `$fn` directly
- Otherwise: N = `max(5, ceil(360 / $fa), ceil(curve_length / $fs))`
- `curve_length` is the arc length of the longer of the inner/outer rails in mm
- Expose as `compute_n(fn, fa, fs, curve_length) -> int`
- Defaults: `$fn = 0`, `$fa = 12`, `$fs = 2`

---

## SCAD file emission (`scad_writer.py`)

### Registry pattern

`scad_writer.py` maintains a registry of emitter functions. Each emitter is a callable
that takes the computed geometry data and writes one or more `.scad` files to the output
directory. The main pipeline calls `run_all_emitters(data, output_dir)`.

Future mould emitters are added by registering new functions — existing emitters are
never modified.

### Files generated for the prototype model

| File | Variable | Contents |
|------|----------|---------|
| `mug_profile_pts.scad` | `mug_profile` | `[[x, z], ...]` — half-profile for `rotate_extrude` |
| `handle_stations.scad` | `handle_stations` | `[[[x,y,z], ...], ...]` — one closed polygon per station |
| `handle_path.scad` | `handle_path` | `[[x,y,z], ...]` — station centroids (for debugging) |
| `mug_params.scad` | various | `$fn`, `$fa`, `$fs`, bounding box dimensions, attach point coordinates |

All generated files include the header:
```
// Auto-generated by mug-generator — do not edit
```

The static `mug.scad` (and any other files in `scad/`) are copied into the output
directory unchanged.

---

## Static `mug.scad`

```openscad
include <BOSL2/std.scad>
include <BOSL2/skin.scad>

include <generated/mug_profile_pts.scad>
include <generated/handle_stations.scad>
include <generated/mug_params.scad>

module mug_body() {
    rotate_extrude(angle=360, $fn=$fn)
        polygon(mug_profile);
}

module handle() {
    skin(handle_stations, slices=0, method="reindex");
}

union() {
    mug_body();
    handle();
}
```

The static file is intentionally minimal — all geometry lives in the generated data
files. The foot is included in the mug half-profile by the artist; no separate foot
module is needed.

---

## Extension dialog (`mug_generator.inx`)

Parameters exposed in the Inkscape extension dialog:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| Output directory | Path field | — | Where to write generated files |
| `$fn` | Integer | 0 | If > 0, overrides $fa/$fs |
| `$fa` | Float | 12 | Maximum angle per segment (degrees) |
| `$fs` | Float | 2 | Maximum segment length (mm) |
| Preview | Checkbox | off | Show/hide preview overlay |

---

## Preview (`preview.py`)

Draws temporary SVG elements into a scratch layer named `_preview` (created if absent,
cleared on each update, never written to generated scad files, removed on dialog close).

Preview elements:

- **Mug body fill**: mirror the mug body path along its left edge, close the shape,
  fill as a solid — gives a silhouette of the revolved body cross-section
- **Handle section overlay**: draw a solid polygon between the inner and outer rails
  in the shared coordinate space, showing the handle's footprint on the mug surface
- **Endpoint proximity indicators**: highlight the inner/outer rail endpoints with a
  circle whose radius corresponds to the validation tolerance, so the artist can see
  whether their endpoints are close enough to the mug body surface

All preview elements use a distinctive colour (e.g. semi-transparent magenta) and are
grouped under the `_preview` layer so they are clearly distinguishable from working
geometry.

---

## Validation and error handling

| Condition | Action |
|-----------|--------|
| Missing layer | Abort; name the missing layer |
| Wrong path count in a layer | Abort; name the layer and expected count |
| Inner/outer rail endpoint far from mug surface | Warn; continue |
| Side rail width increasing toward endpoint | Abort; saddle computation impossible |
| Side rail zero-width extrapolation very long | Warn; continue |
| Degenerate frame (zero-length tangent) | Warn; flag affected stations in scad comment |
| Output directory not writable | Abort |

---

## Testing strategy

- **Unit tests** for `rail_sampler.py`: synthetic straight-line and circular-arc rails
  with analytically known frames
- **Unit tests** for `profile_transformer.py`: unit square profile with identity frame,
  scaled frame, rotated frame
- **Unit tests** for `side_rail_extender.py`: known linear side rail tapering to zero,
  verify terminal station position
- **Unit tests** for `mug_surface.py`: known profile, verify radius interpolation
- **Unit tests** for `units.py`: all supported unit suffixes
- **Integration test**: run the full pipeline on `fixtures/sample.svg`, diff output
  against checked-in expected `.scad` files in `fixtures/expected/`
- No GUI testing of the Inkscape dialog (too environment-dependent)

Tests go in `tests/` and run with `pytest`. Write tests alongside each module, not at
the end.

---

## Implementation order

1. `units.py` and `svg_layers.py` — foundation; testable immediately with a real SVG
2. `mug_surface.py` — simple; needed by step 4
3. `rail_sampler.py` — core geometry; unit-testable with synthetic data
4. `side_rail_extender.py` — depends on rail_sampler and mug_surface
5. `profile_transformer.py` — depends on rail_sampler output
6. `openscad_params.py` — standalone; simple
7. `scad_writer.py` — straightforward once data structures are defined
8. `mug_generator.inx` + `mug_generator.py` — wire everything together into Inkscape
9. `preview.py` — last, purely additive
10. `mug.scad` static file
11. Integration test and fixture SVG

---

## Future work (not in scope for prototype)

- **Block mould**: register a new emitter in `scad_writer.py`; add `scad/moulds/block_mould.scad`
- **Case mould**: same pattern
- Mould emitters will reuse all existing geometry data; no changes to existing modules