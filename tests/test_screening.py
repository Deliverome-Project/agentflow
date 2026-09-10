import copy
import json

import numpy as np
import pandas as pd
import pytest

from agentflow.demo import make_demo
from agentflow.engine import evaluate, prepare, validate
from agentflow.plot_views import apply_axes, draw_events, subset_indices
from agentflow.plots import new_figure
from agentflow.samples import SampleSession, read_samples
from agentflow.screening import screen_report
from agentflow.workflow import mark_unreviewed


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    return make_demo(tmp_path_factory.mktemp("screen-new") / "demo")


def test_group_colors_and_sample_cache(demo, tmp_path):
    records = read_samples(demo / "workflow/samples.csv")
    recipe = json.loads((demo / "workflow/recipe.json").read_text())
    session = SampleSession(records, limit=2)
    first, masks = session.get(records[0], recipe)
    assert session.get(records[0], recipe)[0] is first
    changed = copy.deepcopy(recipe)
    next(g for g in changed["gates"] if g["name"] == "gfp")["bounds"] = [100, None]
    again, changed_masks = session.get(records[0], changed)
    assert again is first
    assert masks["gfp"].sum() > 0 and changed_masks["gfp"].sum() == 0
    for r in records:
        session.get(r, recipe)
    assert len(session.prepared) == 2
    bad = tmp_path / "bad.csv"
    bad.write_text("sample_id,fcs_path,group,color\na,a.fcs,g,red\nb,b.fcs,g,blue\n")
    with pytest.raises(ValueError, match="Conflicting"):
        read_samples(bad)


def test_display_transforms_do_not_change_gates(demo):
    recipe = json.loads((demo / "workflow/recipe.json").read_text())
    prepared = prepare(demo / "sample-1.fcs", recipe)
    masks = evaluate(prepared, recipe)
    fig = new_figure()
    ax = fig.add_subplot(111)
    for channel in ["BL1-A", "FSC-A"]:
        values = prepared.transformed[channel].to_numpy()
        for kind in ["linear", "asinh", "logicle", "recipe"]:
            ax.clear()
            ax.hist(values, bins=20)
            apply_axes(ax, [channel], recipe, [kind])
            transform = ax.xaxis.get_transform()
            test = values[::200]
            np.testing.assert_allclose(
                transform.inverted().transform(transform.transform(test)), test, atol=1e-6
            )
            fig.canvas.draw()
    np.testing.assert_array_equal(masks["gfp"], evaluate(prepared, recipe)["gfp"])


def test_histogram_normalization_and_scatter_limit():
    fig = new_figure()
    ax = fig.add_subplot(111)
    data = np.arange(1000.0)[:, None]
    draw_events(ax, data, ["A"], normalization="area", bins=np.linspace(0, 1000, 11))
    patch_data = ax.patches[0].get_data()
    assert np.sum(patch_data.values * np.diff(patch_data.edges)) == pytest.approx(1)
    assert len(subset_indices(100000)) == 20000
    np.testing.assert_array_equal(subset_indices(100000), subset_indices(100000))


def test_boolean_coexpression_uses_native_engine(demo):
    recipe = json.loads((demo / "workflow/recipe.json").read_text())
    recipe["gates"].append(
        {
            "name": "both",
            "parent": "live",
            "kind": "boolean",
            "operation": "and",
            "references": ["gfp", "mscarlet"],
            "channels": ["BL1-A", "YL2-A"],
            "reviewed": True,
        }
    )
    prepared = prepare(demo / "sample-3.fcs", recipe)
    masks = evaluate(prepared, recipe)
    np.testing.assert_array_equal(masks["both"], masks["gfp"] & masks["mscarlet"])
    mark_unreviewed(recipe, "gfp")
    assert not recipe["gates"][-1]["reviewed"]
    recipe["gates"][-1]["references"] = ["missing", "gfp"]
    with pytest.raises(ValueError, match="references"):
        validate(recipe)


def test_plate_normalization_replicates_and_atomic_failure(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    rows = []
    for i, value in enumerate([0, 2, 98, 100, 60, 70]):
        rows.append(
            {
                "sample_id": f"s{i}",
                "gate": "gfp",
                "count": int(value),
                "parent_count": 1000,
                "percent_parent": value,
                "metadata:plate": "p1",
                "metadata:well": f"A0{i + 1}",
                "metadata:group": "controls" if i < 4 else "treatment",
                "metadata:control_role": "negative" if i < 2 else "positive" if i < 4 else "sample",
            }
        )
    pd.DataFrame(rows).to_csv(run / "summary.csv", index=False)
    out = tmp_path / "report"
    result = screen_report(run, out, "gfp", hit_threshold=50)
    assert result.qc_pass.all()  # Negative population with zero positives is valid.
    assert result.loc[4, "percent_control"] == pytest.approx(100 * 59 / 98)
    assert result.hit.sum() == 2
    plate = pd.read_csv(out / "plates.csv").iloc[0]
    assert plate.z_prime == pytest.approx(1 - 3 * (2 * np.sqrt(2)) / 98)
    assert (out / "plate-001.png").exists()
    assert pd.read_csv(out / "replicates.csv").wells.sum() == 6
    rows[1]["metadata:well"] = "A01"
    pd.DataFrame(rows).to_csv(run / "summary.csv", index=False)
    with pytest.raises(ValueError, match="Duplicate well"):
        screen_report(run, tmp_path / "failed", "gfp")
    assert not (tmp_path / "failed").exists()


def test_explicit_sample_matrix_assignment_and_cache(demo, tmp_path, monkeypatch):
    from agentflow import cache as cache_module
    from agentflow.samples import sample_recipe

    records = read_samples(demo / "workflow/samples.csv")
    recipe = json.loads((demo / "workflow/recipe.json").read_text())
    record = dict(records[0], compensation_path=str(demo / "compensation.json"))
    base = copy.deepcopy(recipe)
    base["compensation"] = {"mode": "none"}
    resolved = sample_recipe(base, record)
    assert resolved["compensation"]["mode"] == "matrix"
    assert base["compensation"]["mode"] == "none"
    manifest = tmp_path / "samples.csv"
    pd.DataFrame([record]).to_csv(manifest, index=False)
    path = tmp_path / "recipe.json"
    path.write_text(json.dumps(base))
    cache = tmp_path / "cache"
    first = cache_module.run_cached(manifest, path, tmp_path / "run1", cache)

    def unexpected(*args, **kwargs):
        raise AssertionError("A verified cache hit should not recompute the batch")

    monkeypatch.setattr(cache_module, "run_batch", unexpected)
    second = cache_module.run_cached(manifest, path, tmp_path / "run2", cache)
    pd.testing.assert_frame_equal(first, second)
    entry = cache / cache_module.cache_key(manifest, path)
    (entry / "summary.csv").write_text("corrupt")
    assert not cache_module.valid_cache(entry)
