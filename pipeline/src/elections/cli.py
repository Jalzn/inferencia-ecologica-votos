"""Command-line entry point: sources, analysis runs, and public releases."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from elections.sources.registry import DEFAULT_RAW_ROOT, REPOSITORY_ROOT

DEFAULT_SPEC = REPOSITORY_ROOT / "data/specs/2026-v3.json"
DEFAULT_CACHE = REPOSITORY_ROOT / "data/cache"
DEFAULT_RUNS = REPOSITORY_ROOT / "data/runs"


def main() -> None:
    parser = argparse.ArgumentParser(prog="elections")
    commands = parser.add_subparsers(dest="command", required=True)
    sources = commands.add_parser("sources", help="Verify or fetch the pinned TSE and IBGE inputs")
    sources.add_argument("action", choices=["verify", "fetch"])
    sources.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    sources.add_argument("--mirror", type=Path, action="append", default=[],
                         help="Local directory searched for files with matching size and SHA-256")
    analyze = commands.add_parser("analyze", help="Build the section panel and run a declared analysis")
    analyze.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    analyze.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    analyze.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    analyze.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    export = commands.add_parser("export", help="Export a public release from an analysis run")
    export.add_argument("--run", type=Path, required=True)
    export.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--fixture", action="store_true", help="Export the small real-data development release")
    export.add_argument("--overwrite", action="store_true", help="Replace an existing release directory")
    validate = commands.add_parser("validate-release", help="Check hashes, schema, coverage, and conservation")
    validate.add_argument("--release", type=Path, required=True)
    validate.add_argument("--require-full", action="store_true",
                          help="Require a full release analyzed and exported from committed, unmodified code")
    validate.add_argument("--deep-schema", action="store_true")
    validate.add_argument("--run", type=Path, help="Also compare every published value with this analysis run")
    validate.add_argument("--raw-root", type=Path, help="With --run, also require byte-identical regenerated resources")
    args = parser.parse_args()

    if args.command == "sources":
        from elections.sources.registry import fetch_sources, verify_sources
        result = verify_sources(args.raw_root) if args.action == "verify" else fetch_sources(args.raw_root, args.mirror)
    elif args.command == "analyze":
        from elections.analysis.run import load_or_build_panel, run_analysis
        from elections.analysis.specification import load_spec
        panel = load_or_build_panel(args.raw_root, args.cache)
        spec = load_spec(args.spec)
        results = run_analysis(panel, spec)
        directory = args.runs / results.metadata["runId"]
        if directory.exists():
            raise SystemExit(f"{directory} already exists; identical inputs and code produced it before")
        results.save(directory)
        result = {"run": str(directory), "selectedModel": results.metadata["selectedModel"],
                  "code": results.metadata["code"], "elapsedSeconds": results.metadata["elapsedSeconds"]}
    elif args.command == "export":
        from elections.export.release import export_release
        result = export_release(args.run, args.raw_root, args.output, args.fixture, args.overwrite)
    else:
        from elections.export.verify import validate_release, verify_against_run
        result = validate_release(args.release, args.require_full, args.deep_schema)
        if args.run:
            result["run"] = verify_against_run(args.release, args.run, args.raw_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
