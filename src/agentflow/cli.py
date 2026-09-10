"""Inspect FCS files, edit gates, and rerun screen analyses."""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from .batch import run_batch
from .engine import evaluate, flowkit, load_recipe, prepare, validate


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Print detector names and metadata as JSON")
    inspect.add_argument("sample")
    edit = commands.add_parser("edit", help="Open one gate; save closes the window and returns success")
    edit.add_argument("sample")
    edit.add_argument("--recipe", required=True)
    edit.add_argument("--gate", required=True)
    edit.add_argument("--x", help="Detector name when creating a gate")
    edit.add_argument("--y", help="Detector name when creating a gate")
    edit.add_argument("--parent", default="root")
    edit.add_argument("--kind", choices=["polygon", "rectangle"], default="polygon")
    edit.add_argument("--compensation", choices=["none", "fcs"], help="Required for a new recipe")
    run = commands.add_parser("run", help="Run a sample CSV without opening any GUI")
    run.add_argument("samples")
    run.add_argument("--recipe", required=True)
    run.add_argument("--out", required=True, help="New output directory (never overwrites a run)")
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            sample = flowkit().Sample(args.sample)
            print(
                json.dumps(
                    {
                        "channels": sample.pnn_labels,
                        "markers": sample.pns_labels,
                        "events": sample.event_count,
                    },
                    indent=2,
                )
            )
        elif args.command == "run":
            run_batch(args.samples, args.recipe, args.out)
        else:
            path = Path(args.recipe)
            if path.exists():
                recipe = load_recipe(path)
                if args.compensation and args.compensation != recipe["compensation"]["mode"]:
                    raise ValueError("Existing recipe controls compensation; edit the recipe explicitly")
            else:
                if not args.compensation:
                    raise ValueError("New recipes require --compensation none or fcs")
                recipe = {
                    "version": 1,
                    "compensation": {"mode": args.compensation},
                    "transforms": {},
                    "gates": [],
                }
            found = next((g for g in recipe["gates"] if g["name"] == args.gate), None)
            if not found:
                if not args.x or not args.y:
                    raise ValueError("New gates require --x and --y detector names")
                for channel in [args.x, args.y]:
                    recipe["transforms"].setdefault(channel, {"kind": "linear"})
            validate(recipe)
            prepared = prepare(args.sample, recipe)
            frame = prepared.transformed
            if not found:
                masks = evaluate(prepared, recipe)
                if args.parent not in masks or not masks[args.parent].any():
                    raise ValueError("Parent must exist and contain events")
                points = frame.loc[masks[args.parent], [args.x, args.y]].to_numpy()
                low, high = np.quantile(points, [0.05, 0.95], axis=0)
                gate = {
                    "name": args.gate,
                    "parent": args.parent,
                    "kind": args.kind,
                    "channels": [args.x, args.y],
                }
                if args.kind == "polygon":
                    gate["vertices"] = [low.tolist(), [high[0], low[1]], high.tolist(), [low[0], high[1]]]
                else:
                    gate["bounds"] = [low[0], high[0], low[1], high[1]]
                recipe["gates"].append(gate)
            validate(recipe)
            import matplotlib

            matplotlib.use("QtAgg")
            from .editor import GateEditor

            editor = GateEditor(prepared, recipe, args.gate, path)
            editor.plt.show(block=True)
            print(json.dumps({"status": "saved" if editor.saved else "cancelled", "recipe": str(path)}))
            return 0 if editor.saved else 2
    except (ValueError, KeyError, OSError, ImportError, TypeError) as error:
        print(json.dumps({"status": "error", "message": str(error)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
