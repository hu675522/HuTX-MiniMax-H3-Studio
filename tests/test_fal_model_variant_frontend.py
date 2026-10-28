from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_model_selector_is_first_and_legacy_workflows_restore_without_shift():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for frontend workflow migration testing")
    source = (ROOT / "web/js/fal_h3_max_model_variant.js").read_text(encoding="utf-8")
    source = source.replace('import { app } from "../../../scripts/app.js";', "")
    fixture = json.loads((ROOT / "tests/fixtures/v01_legacy_fal_workflow.json").read_text(encoding="utf-8"))
    saved_node = next(item for item in fixture["nodes"] if item["type"] == "FalH3MaxVideoGH")
    script = r"""
import assert from 'node:assert/strict';
let extension;
const app = { registerExtension(value) { extension = value; } };
""" + source + r"""
class Node {
    constructor(control = true) {
        this.widgets = [
            { name: 'execution_mode', value: 'dry_run' },
            { name: 'resolution', value: '768P' },
            { name: 'prompt_expansion_mode', value: 'balanced' },
            { name: 'seed', value: -1 },
            ...(control ? [{ name: 'control_after_generate', value: 'randomize' }] : []),
            { name: 'enable_safety_checker', value: true },
            { name: 'max_estimated_cost', value: 2 },
            { name: 'model_variant', value: 'H3 Max' },
        ];
        this.onNodeCreated();
    }
    configure(info) {
        this.info = info;
        // Match the installed LiteGraph named and positional restore behavior.
        this.widgets.forEach((widget, index) => {
            if (info.widgets_values_named && widget.name in info.widgets_values_named) {
                widget.value = info.widgets_values_named[widget.name];
            } else if (!info.widgets_values_named && index < (info.widgets_values?.length ?? 0)) {
                widget.value = info.widgets_values[index];
            }
        });
    }
    values() { return Object.fromEntries(this.widgets.map(w => [w.name, w.value])); }
    serialize() {
        return { ...this.info, widgets_values: this.widgets.map(w => w.value),
                 widgets_values_named: this.values() };
    }
}
extension.beforeRegisterNodeDef(Node, {name: 'FalH3MaxVideoGH'});
const saved = SAVED;
const before = JSON.stringify(saved);
const old = new Node();
assert.equal(old.widgets[0].name, 'model_variant');
old.configure(saved);
assert.equal(JSON.stringify(saved), before);
assert.equal(old.values().model_variant, 'H3 Max');
assert.equal(old.values().resolution, '480P');
assert.equal(old.values().seed, -1);
assert.equal(old.values().control_after_generate, 'randomize');
assert.equal(old.values().enable_safety_checker, true);
assert.equal(old.values().max_estimated_cost, 2);
assert.deepEqual(old.info.inputs, saved.inputs);
assert.deepEqual(old.info.outputs, saved.outputs);
// Existing seed-control values survive unmodified.
const withControl = new Node();
withControl.configure({...saved, widgets_values:['generate','480P','quality',81,'fixed',false,0.30]});
assert.deepEqual(withControl.values(), {
    model_variant:'H3 Max', execution_mode:'generate', resolution:'480P',
    prompt_expansion_mode:'quality', seed:81, control_after_generate:'fixed',
    enable_safety_checker:false, max_estimated_cost:0.30,
});
// Turbo round-trip, clone, and subsequent configure preserve the chosen variant.
withControl.widgets[0].value = 'H3 Max Turbo';
const turbo = new Node();
turbo.configure(withControl.serialize());
assert.deepEqual(turbo.values(), withControl.values());
turbo.configure(turbo.serialize());
assert.equal(turbo.values().model_variant, 'H3 Max Turbo');
const positional = new Node();
const positionalInfo = withControl.serialize();
delete positionalInfo.widgets_values_named;
positional.configure(positionalInfo);
assert.deepEqual(positional.values(), withControl.values());
// Named old workflows without model_variant also default to Max.
const named = new Node();
named.configure({...saved, widgets_values_named:{resolution:'480P',seed:91}});
assert.equal(named.values().model_variant, 'H3 Max');
assert.equal(named.values().seed, 91);
// Native optional-widget order is supported if it was saved before JS reload.
const trailing = new Node(false);
trailing.configure({...saved, widgets_values:[...saved.widgets_values,'H3 Max Turbo']});
assert.equal(trailing.values().model_variant, 'H3 Max Turbo');
assert.equal(trailing.values().max_estimated_cost, 2);
console.log('legacy/seed-control/named/positional/Turbo round-trip: passed');
""".replace("SAVED", json.dumps(saved_node))
    completed = subprocess.run([node, "--input-type=module", "--eval", script],
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
