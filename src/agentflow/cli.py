"""CLI for headless screens and optional human gate review."""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from .batch import run_batch
from .compensation import control_diagnostics, estimate_controls, load_matrix, matrix_diagnostic, save_matrix
from .engine import build_strategy, evaluate, flowkit, load_recipe, prepare, validate
from .workflow import inspect_sample, scaffold


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Show acquired detectors, marker names and compensation")
    inspect.add_argument("sample")
    init = commands.add_parser("init", help="Create a draft workflow and sample sheet")
    init.add_argument("sample")
    init.add_argument("--out", required=True)
    init.add_argument("--example", action="store_true", help="Mark every output DUMMY / EXAMPLE")
    init.add_argument("--compensation", choices=["none", "fcs"], default="fcs")
    init.add_argument("--matrix", help="Explicit matrix JSON/CSV/TSV overrides embedded compensation")
    for role in ("live", "gfp", "mscarlet", "cy5"):
        init.add_argument("--" + role, help="Acquired detector to assign explicitly")
    edit = commands.add_parser("edit", help="Open the full gate workflow or a named gate")
    edit.add_argument("sample")
    edit.add_argument("--recipe", required=True)
    edit.add_argument("--gate")
    edit.add_argument("--x")
    edit.add_argument("--y")
    edit.add_argument("--parent", default="root")
    edit.add_argument("--kind", choices=["polygon", "rectangle", "range"], default="polygon")
    edit.add_argument("--compensation", choices=["none", "fcs"])
    run = commands.add_parser("run", help="Analyze every sample and write a report without opening a GUI")
    run.add_argument("samples")
    run.add_argument("--recipe", required=True)
    run.add_argument("--out", required=True)
    check = commands.add_parser("validate", help="Validate a saved recipe")
    check.add_argument("recipe")
    export = commands.add_parser("export-gml", help="Export gates, transforms and resolved compensation")
    export.add_argument("sample")
    export.add_argument("--recipe", required=True)
    export.add_argument("--out", required=True)
    comp = commands.add_parser("compensation", help="Import or estimate a labelled spillover matrix")
    sub = comp.add_subparsers(dest="operation", required=True)
    imp = sub.add_parser("import")
    imp.add_argument("matrix")
    imp.add_argument("--out", required=True)
    est = sub.add_parser("estimate")
    est.add_argument("controls")
    est.add_argument("--out", required=True)
    demo = commands.add_parser("demo", help="Generate a fully synthetic multi-channel screen and controls")
    demo.add_argument("--out", required=True)
    return result


def open_editor(args):
    path = Path(args.recipe)
    if path.exists():
        recipe = load_recipe(path)
        if args.compensation and args.compensation != recipe["compensation"]["mode"]:
            raise ValueError("Existing recipe controls compensation; use the matrix loader in the editor")
    else:
        if not args.compensation or not args.gate:
            raise ValueError("Use init first, or provide --gate and --compensation for a new recipe")
        recipe = {"version": 1, "compensation": {"mode": args.compensation}, "transforms": {}, "gates": []}
    found = next((g for g in recipe["gates"] if g["name"] == args.gate), None)
    pending = {p["name"] for p in recipe.get("pending_gates", [])}
    if args.gate and not found and args.gate not in pending:
        if not args.x or (args.kind != "range" and not args.y):
            raise ValueError("New gates need --x and, for 2D gates, --y")
        channels = [args.x] if args.kind == "range" else [args.x, args.y]
        for channel in channels:
            recipe["transforms"].setdefault(channel, {"kind": "linear"})
        prepared = prepare(args.sample, recipe)
        masks = evaluate(prepared, recipe)
        if args.parent not in masks or not masks[args.parent].any():
            raise ValueError("Parent must exist and contain events")
        low, high = np.quantile(prepared.transformed.loc[masks[args.parent], channels], [0.05, 0.95], axis=0)
        gate = {
            "name": args.gate,
            "parent": args.parent,
            "kind": args.kind,
            "channels": channels,
            "reviewed": False,
        }
        if args.kind == "polygon":
            gate["vertices"] = [low.tolist(), [high[0], low[1]], high.tolist(), [low[0], high[1]]]
        elif args.kind == "rectangle":
            gate["bounds"] = [low[0], high[0], low[1], high[1]]
        else:
            gate["bounds"] = [float(low[0]), float(high[0])]
        recipe["gates"].append(gate)
    validate(recipe)
    prepared = prepare(args.sample, recipe)
    import matplotlib

    matplotlib.use("QtAgg")
    from .editor import GateEditor

    editor = GateEditor(prepared, recipe, args.gate, path)
    editor.plt.show(block=True)
    print(json.dumps({"status": "saved" if editor.saved else "cancelled", "recipe": str(path)}))
    return 0 if editor.saved else 2


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "inspect":
            print(json.dumps(inspect_sample(args.sample), indent=2))
        elif args.command == "init":
            scaffold(
                args.sample,
                args.out,
                {r: getattr(args, r) for r in ("live", "gfp", "mscarlet", "cy5")},
                args.example,
                args.compensation,
                args.matrix,
            )
            print(
                json.dumps({"status": "created", "output": args.out, "review": "draft gates require review"})
            )
        elif args.command == "run":
            run_batch(args.samples, args.recipe, args.out)
        elif args.command == "validate":
            load_recipe(args.recipe)
            print(json.dumps({"status": "valid"}))
        elif args.command == "edit":
            return open_editor(args)
        elif args.command == "export-gml":
            recipe = load_recipe(args.recipe)
            prepared = prepare(args.sample, recipe)
            with Path(args.out).open("xb") as handle:
                flowkit().export_gatingml(build_strategy(recipe, prepared.matrix), handle)
            print(json.dumps({"status": "exported", "output": args.out}))
        elif args.command == "compensation":
            spec = (
                load_matrix(args.matrix) if args.operation == "import" else estimate_controls(args.controls)
            )
            save_matrix(spec, args.out)
            if args.operation == "estimate":
                control_diagnostics(args.controls, spec, Path(args.out).with_suffix(".controls"))
            diagnostic = Path(args.out).with_suffix(".png")
            if not diagnostic.exists():
                matrix_diagnostic(spec, diagnostic)
            print(
                json.dumps(
                    {
                        "status": "saved",
                        "output": args.out,
                        "review": "inspect controls and matrix before use",
                    }
                )
            )
        elif args.command == "demo":
            from .demo import make_demo

            make_demo(args.out)
            print(json.dumps({"status": "created", "output": args.out, "is_example": True}))
    except (
        ValueError,
        KeyError,
        OSError,
        ImportError,
        TypeError,
        IndexError,
        np.linalg.LinAlgError,
    ) as error:
        print(json.dumps({"status": "error", "message": str(error)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
