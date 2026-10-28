from __future__ import annotations

import builtins
import importlib
import sys
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "hutx_minimax_h3_testpkg"


def test_cloud_node_source_has_no_local_model_or_conditioning_imports():
    source = (PROJECT_ROOT / "cloud_video_nodes.py").read_text(encoding="utf-8")
    forbidden = [
        "import torch",
        "import conditioning",
        "from .conditioning",
        "build_conditioning",
        "CLIPLoader",
        "VAELoader",
        "VideoVAE",
        "AudioVAE",
        "latent",
    ]
    for marker in forbidden:
        assert marker not in source


def test_import_and_execute_cloud_node_do_not_open_media_or_load_local_modules(monkeypatch):
    class FakeNodeOutput:
        def __init__(self, *values):
            self.values = values

    fake_io = types.SimpleNamespace(ComfyNode=object, NodeOutput=FakeNodeOutput)
    fake_latest = types.ModuleType("comfy_api.latest")
    fake_latest.io = fake_io
    fake_comfy_api = types.ModuleType("comfy_api")
    fake_comfy_api.latest = fake_latest
    monkeypatch.setitem(sys.modules, "comfy_api", fake_comfy_api)
    monkeypatch.setitem(sys.modules, "comfy_api.latest", fake_latest)

    module_name = f"{PACKAGE}.cloud_video_nodes"
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    before = set(sys.modules)
    module = importlib.import_module(module_name)
    newly_loaded = set(sys.modules) - before
    assert "conditioning" not in newly_loaded
    assert f"{PACKAGE}.conditioning" not in newly_loaded
    assert "nodes" not in newly_loaded
    assert f"{PACKAGE}.nodes" not in newly_loaded
    assert "torch" not in newly_loaded

    calls = {"open": 0, "build_conditioning": 0, "clip": 0, "vae": 0}

    def forbidden_open(*args, **kwargs):
        calls["open"] += 1
        raise AssertionError("Cloud request construction must not open media files")

    monkeypatch.setattr(builtins, "open", forbidden_open)
    result = module.GHCloudVideoInputGH.execute(
        main_mode="text_keyframes",
        prompt="cloud-only request",
        aspect="adaptive",
        duration_seconds=5,
        first_frame="frames/first.png",
    )
    request = result.values[0]
    assert request["kind"] == "gh_video_request"
    assert request["resolved_task"] == "i2v"
    assert calls == {"open": 0, "build_conditioning": 0, "clip": 0, "vae": 0}
