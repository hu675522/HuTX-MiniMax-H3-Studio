from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_MODULE = PROJECT_ROOT / "web" / "js" / "fal_h3_max_timing_state.js"
NODE = shutil.which("node")


def _run_state_test(body: str) -> None:
    if NODE is None:
        pytest.skip("Node.js is required for frontend timing state tests")
    state_source = STATE_MODULE.read_text(encoding="utf-8").replace(
        "export class FalPromptTimingState", "class FalPromptTimingState", 1
    )
    script = state_source + "\nconst state = new FalPromptTimingState();\n" + body
    completed = subprocess.run(
        [NODE, "--eval", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_frontend_uses_official_queue_and_executed_events_with_prompt_correlation():
    source = (
        PROJECT_ROOT / "web" / "js" / "fal_h3_max_timing.js"
    ).read_text(encoding="utf-8")
    assert 'addEventListener("promptQueueing"' in source
    assert 'addEventListener("executed"' in source
    assert "response?.prompt_id" in source
    assert "detail?.prompt_id" in source
    assert "Queue → VIDEO:" in source
    assert "Date.now() - timing.queueStartedAtMs" in source
    assert "new WeakMap()" in source
    assert "findPromptNode(promptId, executedIds)" in source
    assert 'addEventListener("execution_success", clearPromptTiming)' in source


def test_two_prompt_ids_do_not_cross_node_timing():
    _run_state_test(
        """
state.recordQueueStart(1000, 1);
let queueStart = state.claimQueueStart();
state.associatePrompt("prompt-a", ["node-a"], queueStart);
state.finishQueueAttempt();
state.recordQueueStart(2000, 1);
queueStart = state.claimQueueStart();
state.associatePrompt("prompt-b", ["node-b"], queueStart);
state.finishQueueAttempt();
if (state.findPromptNode("prompt-a", ["node-a"]).queueStartedAtMs !== 1000) process.exit(1);
if (state.findPromptNode("prompt-b", ["node-b"]).queueStartedAtMs !== 2000) process.exit(2);
if (state.findPromptNode("prompt-a", ["node-b"]) !== null) process.exit(3);
"""
    )


def test_same_fal_node_in_consecutive_queues_keeps_both_prompt_starts():
    _run_state_test(
        """
state.recordQueueStart(3000, 1);
let queueStart = state.claimQueueStart();
state.associatePrompt("prompt-first", ["node-7"], queueStart);
state.finishQueueAttempt();
state.recordQueueStart(4500, 1);
queueStart = state.claimQueueStart();
state.associatePrompt("prompt-second", ["node-7"], queueStart);
state.finishQueueAttempt();
if (state.findPromptNode("prompt-first", ["node-7"]).queueStartedAtMs !== 3000) process.exit(1);
if (state.findPromptNode("prompt-second", ["node-7"]).queueStartedAtMs !== 4500) process.exit(2);
"""
    )


def test_frontend_cleanup_removes_old_prompt_timing_state():
    _run_state_test(
        """
state.recordQueueStart(5000, 1);
const queueStart = state.claimQueueStart();
state.associatePrompt("prompt-cleanup", ["node-9"], queueStart);
state.finishQueueAttempt();
if (state.promptCount !== 1) process.exit(1);
state.cleanupPrompt("prompt-cleanup");
if (state.promptCount !== 0) process.exit(2);
if (state.findPromptNode("prompt-cleanup", ["node-9"]) !== null) process.exit(3);
"""
    )
