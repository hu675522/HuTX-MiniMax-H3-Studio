from __future__ import annotations

import ast
import functools
import importlib.util
import json
import re
import shutil
import subprocess
import threading
import types
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen

from hutx_minimax_h3_testpkg.plugin_meta import (
    PLUGIN_NAME, PLUGIN_DISPLAY_NAME, PLUGIN_VERSION, PLUGIN_VENDOR, NODE_CATEGORY,
)

ROOT = Path(__file__).resolve().parents[1]
BASE = f"/extensions/{PLUGIN_NAME}/"


def test_canonical_identity_and_unchanged_web_directory():
    assert (PLUGIN_NAME, PLUGIN_DISPLAY_NAME, PLUGIN_VERSION, PLUGIN_VENDOR) == (
        "HuTX-MiniMax-H3-Studio", "HuTX · MiniMax H3 Studio", "0.3.2.2", "HuTX",
    )
    assert NODE_CATEGORY == "HuTX/MiniMax H3 Studio"
    tree = ast.parse((ROOT / "__init__.py").read_text(encoding="utf-8"))
    assignment = next(item for item in tree.body if isinstance(item, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "WEB_DIRECTORY" for t in item.targets))
    assert ast.literal_eval(assignment.value) == "./web"


def static_urls():
    urls = set()
    for path in (ROOT / "web/js").glob("*.js"):
        text = path.read_text(encoding="utf-8")
        assert "/extensions/Goohai-MiniMax-H3_Integration/" not in text
        parent = BASE + "js/" + path.name
        urls.add(parent)
        imports = re.findall(r'\bfrom\s+[\"\']([^\"\']+)[\"\']', text)
        imports += re.findall(r'new URL\([\"\']([^\"\']+)[\"\'],\s*import\.meta\.url\)', text)
        imports += re.findall(r'\bimport\([\"\']([^\"\']+)[\"\']\)', text)
        for relative in imports:
            resolved = urljoin(parent, relative)
            if resolved.startswith("/scripts/"):
                assert resolved in {"/scripts/app.js", "/scripts/api.js"}
            else:
                assert resolved.startswith(BASE), (path, relative, resolved)
                assert (ROOT / "web" / resolved[len(BASE):]).is_file(), resolved
                urls.add(resolved)
    return urls


def test_every_frontend_entry_import_and_audio_returns_200_at_new_extension_base():
    # Standard static-file HTTP serving at the same extension URL prefix used by
    # ComfyUI. This does NOT contact a model/provider or pretend to launch ComfyUI.
    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if not urlsplit(self.path).path.startswith(BASE):
                self.send_error(404)
                return
            self.path = self.path[len(BASE) - 1:]
            super().do_GET()

        def log_message(self, *args):
            pass

    handler = functools.partial(Handler, directory=str(ROOT / "web"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        urls = static_urls()
        assert BASE + "audio/done.mp3" in urls
        for path in urls:
            with urlopen(f"http://127.0.0.1:{server.server_port}{path}", timeout=5) as response:
                assert response.status == 200
                assert response.read()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_extension_names_migrate_without_renaming_node_types_or_state_keys():
    names = set()
    for path in (ROOT / "web/js").glob("*.js"):
        text = path.read_text(encoding="utf-8")
        names.update(re.findall(r'\bname:\s*"(HuTX\.MiniMaxH3Studio\.[^"]+)"', text))
        assert not re.search(r'\bname:\s*"[Gg]oohai\.', text)
    assert names == {"HuTX.MiniMaxH3Studio." + suffix for suffix in (
        "LocalStudio", "CloudVideoInput", "FalVideo", "Timing", "FalCredentials",
    )}
    cloud = (ROOT / "web/js/gh_cloud_video_input.js").read_text(encoding="utf-8")
    local = (ROOT / "web/js/minimax_h3_integration.js").read_text(encoding="utf-8")
    assert 'const NODE = "GHCloudVideoInputGH"' in cloud
    assert '"gh_cloud_video_state"' in cloud and '"gh_cloud_state_json"' in cloud
    assert 'const NODE = "MiniMaxH3IntegrationGH"' in local
    assert '"gh_h3_state"' in local and '"gh_state_json"' in local


def test_both_locales_keep_class_keys_and_only_change_display_identity():
    expected = {"MiniMaxH3IntegrationGH", "MiniMaxH3IntegrationAdapterGH", "MiniMaxH3DualClockT8GH",
                "MiniMaxH3AVDecodeT8GH", "GHCloudVideoInputGH", "FalH3MaxVideoGH", "GHLocalVideoInputGH",
                "GHLocalVideoInputDualEngineGH", "GHLocalVideoDualEngineOutputGH", "HuTXH3PreserveFirstPassAudioGH",
                "HuTXH3HyperFlowCompatibility", "HuTXH3HyperFlowPatch", "HuTXH3HyperFlowSampler"}
    for language in ("en", "zh"):
        definitions = json.loads((ROOT / f"locales/{language}/nodeDefs.json").read_text(encoding="utf-8"))
        assert set(definitions) == expected
        assert all(item["display_name"].startswith("HuTX") for item in definitions.values())


def test_optimizer_package_owns_compat_routes_once_across_import_aliases():
    spec = importlib.util.find_spec("hutx_minimax_h3_testpkg.prompt_optimizer")
    assert Path(spec.origin) == ROOT / "prompt_optimizer/__init__.py"
    tree = ast.parse((ROOT / "prompt_optimizer/legacy.py").read_text(encoding="utf-8"))
    definition = next(item for item in tree.body if isinstance(item, ast.FunctionDef)
                      and item.name == "register_prompt_optimizer_routes")
    registrations = []
    class Routes:
        def __getattr__(self, method):
            def route(path):
                def register(callback):
                    assert (method, path) not in registrations
                    registrations.append((method, path))
                    return callback
                return register
            return route
    server = types.SimpleNamespace(routes=Routes())
    for _ in range(2):
        namespace = {"__package__": "hutx_minimax_h3_testpkg.prompt_optimizer", "_ROUTES_REGISTERED": False, "PromptServer": types.SimpleNamespace(instance=server)}
        for callback in ("get_prompt_optimizer_config", "list_prompt_optimizer_models", "refresh_runninghub_models",
                         "save_prompt_optimizer_config", "store_prompt_optimizer_secret", "optimize_prompt",
                         "start_prompt_optimization", "prompt_optimization_status", "cancel_prompt_optimization"):
            namespace[callback] = lambda: None
        exec(compile(ast.Module(body=[definition], type_ignores=[]), "route-owner", "exec"), namespace)
        assert namespace["register_prompt_optimizer_routes"]() is True
        assert namespace["register_prompt_optimizer_routes"]() is True
    assert len(registrations) == 12
    assert sum(path.startswith("/goohai/minimax-h3/prompt-optimizer/") for _, path in registrations) == 9
    assert {(method, path) for method, path in registrations if path.startswith("/hutx/")} == {
        (method, "/hutx/minimax-h3/prompt-optimizer/credential") for method in ("get", "post", "delete")}


def test_legacy_plugin_identity_workflow_load_migrate_save_reload():
    node = shutil.which("node")
    assert node, "Node.js is required for workflow identity migration testing"
    fixture = json.loads((ROOT / "tests/fixtures/legacy_plugin_identity_workflow.json").read_text(encoding="utf-8"))
    source = (ROOT / "web/js/fal_h3_max_model_variant.js").read_text(encoding="utf-8")
    source = source.replace('import { app } from "../../../scripts/app.js";', "")
    script = "const app={registerExtension(){}};\n" + source + "\nconst saved=" + json.dumps(fixture) + ";\n" + r'''
const workflow=JSON.parse(JSON.stringify(saved));
const fal=workflow.nodes.find(n=>n.type==='FalH3MaxVideoGH');
const names=['model_variant','execution_mode','resolution','prompt_expansion_mode','seed',
    'control_after_generate','enable_safety_checker','max_estimated_cost'];
const widgets=names.map(name=>({name,value:name==='control_after_generate'?'randomize':null}));
Object.assign(fal,migrateModelWidgetValues(fal,widgets));
const reloaded=JSON.parse(JSON.stringify(workflow));
const again=reloaded.nodes.find(n=>n.type==='FalH3MaxVideoGH');
Object.assign(again,migrateModelWidgetValues(again,widgets));
console.log(JSON.stringify({workflow,reloaded}));
'''
    result = subprocess.run([node, "--input-type=module", "--eval", script],
                            capture_output=True, text=True, encoding="utf-8", check=True)
    parsed = json.loads(result.stdout)
    assert parsed["workflow"] == parsed["reloaded"]
    for old, restored in zip(fixture["nodes"], parsed["reloaded"]["nodes"]):
        for key in ("type", "inputs", "outputs", "properties"):
            assert old[key] == restored[key]
        if restored["type"] == "FalH3MaxVideoGH":
            assert restored["widgets_values"][0] == "H3 Max"
    assert fixture["links"] == parsed["reloaded"]["links"]
