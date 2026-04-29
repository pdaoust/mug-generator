#!/usr/bin/env python3
"""Profile OpenSCAD modules by rendering them individually and timing each."""

import argparse
import csv
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from statistics import median

# ---------------------------------------------------------------------------
# Module registries
# ---------------------------------------------------------------------------

MUG_MODULES = [
    "mug_body",
    "handle",
    "mark_stamp",
    "mug_assembly",
]

MOULD_MODULES = [
    "mug_body",
    "mug_solid",
    "handle",
    "mug_positive",
    "mould_hull_2d",
    "mould_outer_hull_2d",
    "full_walls",
    "full_outer_hull",
    "case_half_a",
    "case_half_b",
    "case_base",
    "render_2part",
    "render_3part",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RE_RENDER_TIME = re.compile(
    r"Total rendering time:\s*(\d+):(\d+):(\d+)(?:\.(\d+))?",
)


def parse_render_time(stderr: str) -> float | None:
    """Extract the CGAL render time (seconds) from OpenSCAD stderr."""
    m = _RE_RENDER_TIME.search(stderr)
    if not m:
        return None
    h, mn, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
    frac = int(m.group(4)) if m.group(4) else 0
    # The fractional part is variable-width; normalise to seconds.
    frac_s = frac / (10 ** len(m.group(4))) if m.group(4) else 0.0
    return h * 3600 + mn * 60 + s + frac_s


def _fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    if seconds < 0.05:
        return "~0s"
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(seconds, 60)
    return f"{int(m)}m{s:04.1f}s"


def _pct(value: float | None, baseline: float | None) -> str:
    if value is None or baseline is None or baseline <= 0:
        return "-"
    return f"{100 * value / baseline:.1f}%"


def _delta(value: float | None, noop: float | None) -> float | None:
    if value is None or noop is None:
        return None
    return max(value - noop, 0.0)


# ---------------------------------------------------------------------------
# Core profiling
# ---------------------------------------------------------------------------


def profile_one(
    scad_file: Path,
    module: str | None,
    openscad: str,
    extra_flags: list[str],
) -> dict:
    """Render a single module (or the full file) and return timing data."""
    with tempfile.NamedTemporaryFile(suffix=".off", delete=False) as tmp:
        out_path = tmp.name

    cmd = [openscad, "-o", out_path]
    if module is not None:
        cmd += ["-D", f'_profile_module="{module}"']
    cmd += extra_flags
    cmd.append(str(scad_file))

    t0 = time.monotonic()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        return {
            "module": module or "full",
            "wall_s": None,
            "cgal_s": None,
            "exit_code": -1,
            "error": "timeout (600s)",
        }
    finally:
        Path(out_path).unlink(missing_ok=True)

    elapsed = time.monotonic() - t0
    cgal = parse_render_time(result.stderr)

    entry = {
        "module": module or "full",
        "wall_s": round(elapsed, 2),
        "cgal_s": round(cgal, 2) if cgal is not None else None,
        "exit_code": result.returncode,
    }
    if result.returncode != 0 and module != "noop":
        # Keep last 300 chars of stderr for diagnostics.
        entry["error"] = result.stderr[-300:].strip()
    return entry


def profile_modules(
    scad_file: Path,
    modules: list[str],
    openscad: str,
    extra_flags: list[str],
    repeats: int,
) -> list[dict]:
    """Profile noop + full + each module, returning results."""
    # noop first, then full baseline, then individual modules.
    targets: list[str | None] = ["noop", None] + list(modules)
    results = []

    for target in targets:
        label = target or "full"
        timings_wall: list[float] = []
        timings_cgal: list[float] = []
        last_entry: dict = {}

        for _i in range(repeats):
            entry = profile_one(scad_file, target, openscad, extra_flags)
            last_entry = entry
            if entry.get("wall_s") is not None:
                timings_wall.append(entry["wall_s"])
            if entry.get("cgal_s") is not None:
                timings_cgal.append(entry["cgal_s"])
            if entry.get("exit_code", 0) != 0:
                break  # don't repeat failures

        if repeats == 1:
            results.append(last_entry)
        else:
            results.append({
                "module": label,
                "wall_s": round(median(timings_wall), 2) if timings_wall else None,
                "cgal_s": round(median(timings_cgal), 2) if timings_cgal else None,
                "wall_min": round(min(timings_wall), 2) if timings_wall else None,
                "wall_max": round(max(timings_wall), 2) if timings_wall else None,
                "runs": len(timings_wall),
                "exit_code": last_entry.get("exit_code"),
            })

    return results


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def format_table(scad_name: str, results: list[dict], repeats: int) -> str:
    lines = [f"\n=== PROFILE: {scad_name} ===\n"]

    # Find noop and full baselines.
    noop_wall = None
    full_wall = None
    for r in results:
        if r["module"] == "noop":
            noop_wall = r.get("wall_s")
        elif r["module"] == "full":
            full_wall = r.get("wall_s")

    full_delta = _delta(full_wall, noop_wall)

    if repeats == 1:
        header = (
            f"{'Module':<26} {'Wall Clock':>10}  {'Delta':>10}  "
            f"{'% of Full':>9}"
        )
        sep = "-" * len(header)
        lines.append(header)
        lines.append(sep)
        for r in results:
            d = _delta(r.get("wall_s"), noop_wall)
            tag = ""
            if r["module"] == "noop":
                tag = "  (startup)"
            elif r["module"] == "full":
                tag = "  (baseline)"
            err = (
                f"  ERROR: {r.get('error', '')[:60]}"
                if r.get("exit_code", 0) != 0 else ""
            )
            lines.append(
                f"{r['module']:<26} "
                f"{_fmt_time(r.get('wall_s')):>10}  "
                f"{_fmt_time(d):>10}  "
                f"{_pct(d, full_delta):>9}"
                f"{tag}{err}"
            )
    else:
        header = (
            f"{'Module':<26} {'Median':>8}  {'Delta':>8}  {'Min':>8}  "
            f"{'Max':>8}  {'% of Full':>9}  {'Runs':>4}"
        )
        sep = "-" * len(header)
        lines.append(header)
        lines.append(sep)
        for r in results:
            d = _delta(r.get("wall_s"), noop_wall)
            tag = ""
            if r["module"] == "noop":
                tag = "  (startup)"
            elif r["module"] == "full":
                tag = "  (baseline)"
            lines.append(
                f"{r['module']:<26} "
                f"{_fmt_time(r.get('wall_s')):>8}  "
                f"{_fmt_time(d):>8}  "
                f"{_fmt_time(r.get('wall_min')):>8}  "
                f"{_fmt_time(r.get('wall_max')):>8}  "
                f"{_pct(d, full_delta):>9}  "
                f"{r.get('runs', '-'):>4}"
                f"{tag}"
            )

    lines.append("")
    return "\n".join(lines)


def format_csv(results: list[dict]) -> str:
    buf = io.StringIO()
    if not results:
        return ""
    writer = csv.DictWriter(buf, fieldnames=results[0].keys())
    writer.writeheader()
    writer.writerows(results)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def find_scad_file(scad_dir: Path, name: str) -> Path:
    """Locate a .scad file in the output directory or its scad/ subdirectory."""
    for candidate in [scad_dir / name, scad_dir / "scad" / name]:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"Cannot find {name} in {scad_dir} or {scad_dir / 'scad'}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Profile OpenSCAD mug/mould modules individually.",
    )
    parser.add_argument(
        "scad_dir",
        type=Path,
        help="Directory containing the generated SCAD data files "
             "(mug_params.scad, etc.) and the main .scad files.",
    )
    parser.add_argument(
        "--file",
        choices=["mug", "mould", "both"],
        default="both",
        help="Which SCAD file to profile (default: both).",
    )
    parser.add_argument(
        "--modules",
        default="all",
        help="Comma-separated module names, or 'all' (default: all).",
    )
    parser.add_argument(
        "--openscad",
        default="openscad",
        help="Path to the OpenSCAD binary (default: openscad).",
    )
    parser.add_argument(
        "--flags",
        default="",
        help="Extra OpenSCAD flags, space-separated "
             "(e.g. '--enable=manifold').",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Run each module N times; report min/median/max (default: 1).",
    )
    parser.add_argument(
        "--output",
        choices=["table", "json", "csv"],
        default="table",
        help="Output format (default: table).",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=None,
        help="Write results to a file instead of stdout.",
    )

    args = parser.parse_args()

    if not shutil.which(args.openscad):
        sys.exit(f"Error: OpenSCAD binary not found: {args.openscad}")

    extra_flags = args.flags.split() if args.flags else []
    scad_dir = args.scad_dir.resolve()

    files_to_profile: list[tuple[str, Path, list[str]]] = []

    if args.file in ("mug", "both"):
        path = find_scad_file(scad_dir, "mug.scad")
        mods = MUG_MODULES if args.modules == "all" else args.modules.split(",")
        files_to_profile.append(("mug.scad", path, mods))

    if args.file in ("mould", "both"):
        path = find_scad_file(scad_dir, "case_mould_original.scad")
        mods = MOULD_MODULES if args.modules == "all" else args.modules.split(",")
        files_to_profile.append(("case_mould_original.scad", path, mods))

    all_results: dict[str, list[dict]] = {}

    for scad_name, scad_path, modules in files_to_profile:
        print(
            f"Profiling {scad_name} "
            f"(noop + full + {len(modules)} modules)...",
            file=sys.stderr,
        )
        results = profile_modules(
            scad_path, modules, args.openscad, extra_flags, args.repeat,
        )
        all_results[scad_name] = results

    # Format output.
    if args.output == "json":
        text = json.dumps(all_results, indent=2)
    elif args.output == "csv":
        parts = []
        for scad_name, results in all_results.items():
            for r in results:
                r["file"] = scad_name
            parts.extend(results)
        text = format_csv(parts)
    else:
        text = ""
        for scad_name, results in all_results.items():
            text += format_table(scad_name, results, args.repeat)

    if args.output_file:
        args.output_file.write_text(text)
        print(f"Results written to {args.output_file}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
