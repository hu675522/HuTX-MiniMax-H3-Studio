from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _fal_output_names() -> list[str]:
    tree = ast.parse((PROJECT_ROOT / "fal_nodes.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "FalH3MaxVideoGH":
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            if not isinstance(call.func, ast.Attribute) or call.func.attr != "Schema":
                continue
            outputs = next(keyword.value for keyword in call.keywords if keyword.arg == "outputs")
            assert isinstance(outputs, ast.List)
            return [
                str(ast.literal_eval(item.args[0]))
                for item in outputs.elts
                if isinstance(item, ast.Call) and item.args
            ]
    raise AssertionError("FalH3MaxVideoGH schema was not found")


def test_existing_five_outputs_stay_in_order_and_expanded_prompt_is_appended():
    assert _fal_output_names() == [
        "video",
        "video_url",
        "request_id",
        "endpoint",
        "report",
        "expanded_prompt",
    ]


def test_local_h3_nodes_remain_registered_before_fal_node():
    source = (PROJECT_ROOT / "nodes.py").read_text(encoding="utf-8")
    registration = source[source.index("async def get_node_list") :]
    expected = [
        "MiniMaxH3IntegrationGH",
        "MiniMaxH3IntegrationAdapterGH",
        "MiniMaxH3DualClockT8GH",
        "MiniMaxH3AVDecodeT8GH",
        "GHCloudVideoInputGH",
        "FalH3MaxVideoGH",
    ]
    positions = [registration.index(name) for name in expected]
    assert positions == sorted(positions)


def test_fal_node_keeps_required_integration_input_and_adds_multitype():
    source = (PROJECT_ROOT / "fal_nodes.py").read_text(encoding="utf-8")
    assert '"integration"' in source
    assert "io.MultiType.Input" in source
    assert "MINIMAX_INPUT_TYPE" in source
    assert "GH_VIDEO_REQUEST_INPUT_TYPE" in source
    tree = ast.parse(source)
    integration = next(
        call for call in ast.walk(tree)
        if isinstance(call, ast.Call) and call.args
        and isinstance(call.args[0], ast.Constant) and call.args[0].value == "integration"
    )
    assert not any(keyword.arg == "optional" for keyword in integration.keywords)


def test_model_variant_is_optional_for_old_api_prompts():
    tree = ast.parse((PROJECT_ROOT / "fal_nodes.py").read_text(encoding="utf-8"))
    model = next(
        call for call in ast.walk(tree)
        if isinstance(call, ast.Call) and call.args
        and isinstance(call.args[0], ast.Constant) and call.args[0].value == "model_variant"
    )
    keywords = {item.arg: item.value for item in model.keywords}
    assert ast.literal_eval(keywords["optional"]) is True
    assert keywords["default"].id == "DEFAULT_MODEL_VARIANT"
