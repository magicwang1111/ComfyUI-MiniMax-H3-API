import json
from pathlib import Path


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_all_example_workflows_are_structurally_valid():
    paths = sorted(EXAMPLES.glob("*.json"))
    assert len(paths) == 7
    for path in paths:
        workflow = json.loads(path.read_text(encoding="utf-8"))
        assert workflow["version"] == 0.4
        nodes = {node["id"]: node for node in workflow["nodes"]}
        assert nodes
        for link in workflow["links"]:
            link_id, source_id, source_slot, target_id, target_slot, link_type = link
            assert link_id > 0
            assert source_id in nodes
            assert target_id in nodes
            assert source_slot >= 0
            assert target_slot >= 0
            assert link_type


def test_examples_do_not_contain_api_keys():
    for path in EXAMPLES.glob("*.json"):
        text = path.read_text(encoding="utf-8").lower()
        assert "api_key" not in text
        assert "authorization" not in text

