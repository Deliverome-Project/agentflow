import pytest

from agentflow.demo import make_demo
from agentflow.projects import create_project
from agentflow.samples import read_samples


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    return make_demo(tmp_path_factory.mktemp("import") / "source")


def test_import_fcs_is_atomic_and_preserves_inputs(demo, tmp_path):
    from agentflow.engine import digest, load_recipe

    paths = [demo / "sample-1.fcs", demo / "sample-2.fcs"]
    before = [digest(p) for p in paths]
    out = create_project(paths, tmp_path / "analysis", "none", example=True)
    assert [digest(p) for p in paths] == before
    assert len(read_samples(out / "samples.csv")) == 2
    assert load_recipe(out / "recipe.json")["experiment"]["is_example"]
    with pytest.raises(ValueError, match="new analysis"):
        create_project(paths, out, "none")
    bad = tmp_path / "bad"
    with pytest.raises((OSError, ValueError)):
        create_project([*paths, tmp_path / "missing.fcs"], bad, "none")
    assert not bad.exists()
    assert not list(tmp_path.glob(".agentflow-import-*"))
