"""Offline actual Cloud DOM/controller lifecycle, plus Python UI-state boundary."""
import json
import subprocess

import pytest

from .test_optimizer_persistence import run_panel, run_shared, config_response_from_actual_handler, build
from hutx_minimax_h3_testpkg.gh_video_request import validate_cloud_state_json, normalize_cloud_request
from hutx_minimax_h3_testpkg.fal_models import FalValidationError


def pair(state):
    return [state['optimizer'][key] for key in ('original_prompt', 'optimized_prompt')]


def previous():
    return {'schema_version': 1, 'mode': 'text_keyframes', 'prompt': 'Current user draft.',
            'media': [], 'optimizer': {'optimizer_state_version': 2, 'config': {'prompt_profile': 'structured'},
                                     'original_prompt': 'Previous before.', 'optimized_prompt': 'Previous after.'}}


@pytest.mark.parametrize('automatic', [False, True])
def test_success_destroy_reload_restart_compare_and_profile(monkeypatch, automatic):
    config = config_response_from_actual_handler(monkeypatch)
    result = run_panel(config=config, runtime=True, automatic=automatic, profile='structured',
                       historyActions=[{'type': 'reload'}, {'type': 'configure'}])
    expected = ['A paper boat sails.', 'Optimized paper boat scene.']
    for saved in result['historySnapshots']:
        assert pair(saved['state']) == expected
        assert saved['state']['prompt'] == expected[1]
        assert [view['text'] for view in saved['views']] == expected
        assert all(view['readOnly'] for view in saved['views'])
        assert json.loads(saved['properties']['gh_cloud_video_state']) == saved['state']
        assert saved['state']['optimizer']['config']['prompt_profile'] == 'structured'
    # A fresh Node.js process has no controller/JS memory from the first run.
    restarted = run_panel(state=result['state'], config=config, historyActions=[{'type': 'reload'}])
    assert pair(restarted['state']) == expected
    assert [view['text'] for view in restarted['historySnapshots'][0]['views']] == expected
    wire = next(r['body'] for r in result['requests'] if r['url'].endswith('/optimize'))
    assert 'original_prompt' not in json.dumps(wire)
    assert 'TEST_SECRET_123' not in json.dumps(result['state'])
    request = build(result['state'])
    assert 'optimizer' not in request and 'original_prompt' not in json.dumps(request)
    assert normalize_cloud_request(request).metadata == {'source_node': 'GHCloudVideoInputGH'}


@pytest.mark.parametrize('action,expected', [('edit', 'Manual new text.'), ('restore', 'Previous before.'), ('apply', 'Previous after.')])
def test_current_edits_restore_apply_leave_pair_and_reload(monkeypatch, action, expected):
    result = run_panel(state=previous(), config=config_response_from_actual_handler(monkeypatch),
                       historyActions=[{'type': action, 'value': expected}, {'type': 'reload'}])
    assert result['state']['prompt'] == expected
    assert pair(result['state']) == pair(previous())
    assert not any(r['url'].endswith('/optimize') for r in result['requests'])
    assert build(result['state'])['input_prompt'] == expected


@pytest.mark.parametrize('error', ['Mock provider failure', 'Unknown media label <Picture 9>', 'Missing media label <Picture 1>'])
def test_failed_or_tag_rejected_response_keeps_last_success(monkeypatch, error):
    result = run_panel(state=previous(), config=config_response_from_actual_handler(monkeypatch), runtime=True,
                       optimizeError=error, historyActions=[{'type': 'reload'}])
    assert pair(result['state']) == pair(previous())
    assert result['state']['prompt'] == previous()['prompt']


@pytest.mark.parametrize('operation', ['cancel', 'edit', 'editBack', 'configure', 'duplicate'])
def test_inflight_cancel_edit_reconfigure_and_duplicate_guard(monkeypatch, operation):
    replacement = previous()
    replacement['optimizer']['original_prompt'] = 'Loaded before.'
    replacement['optimizer']['optimized_prompt'] = 'Loaded after.'
    result = run_panel(state=previous(), config=config_response_from_actual_handler(monkeypatch), runtime=True,
                       duringOptimize=operation, replacementState=replacement, historyActions=[{'type': 'reload'}])
    assert len([r for r in result['requests'] if r['url'].endswith('/optimize')]) == 1
    if operation == 'duplicate':
        assert pair(result['state']) == [previous()['prompt'], 'Optimized paper boat scene.']
    else:
        assert pair(result['state']) == pair(replacement if operation == 'configure' else previous())
        assert result['state']['prompt'] == ('User edited while waiting.' if operation == 'edit' else previous()['prompt'])


def test_old_workflow_does_not_invent_history(monkeypatch):
    state = previous(); state.pop('optimizer')
    result = run_panel(state=state, config=config_response_from_actual_handler(monkeypatch), locale='zh',
                       historyActions=[{'type': 'reload'}])
    assert result['state']['prompt'] == state['prompt']
    assert pair(result['state']) == ['', '']
    assert result['historySnapshots'][0]['empty'] == '暂无优化记录'


@pytest.mark.parametrize('bad', [None, 3, [], {'api_key': 'TEST_SECRET'}, {'credential_ref': 'ghopt_test'},
                                {'config': {}}, {'headers': {}}, {'runtime': {}}, {'model': {}}, {'base64': 'AAAA'}])
def test_malformed_or_structured_history_rejected_both_boundaries(bad):
    state = previous(); state['optimizer']['original_prompt'] = bad
    with pytest.raises(FalValidationError): validate_cloud_state_json(state)
    expression = 'try { validateCloudPromptHistory(' + json.dumps(state['optimizer']) + '); } catch(e) { console.log(e.message); }'
    result = run_shared(expression)
    assert 'must both be strings' in result.stdout
    assert 'TEST_SECRET' not in result.stdout
    with pytest.raises(subprocess.CalledProcessError): run_panel(state=state)


@pytest.mark.parametrize('field', ['credential_ref', 'runtime', 'headers', 'secret_store', 'model', 'prompt_history'])
def test_unknown_history_state_fields_rejected(field):
    state = previous(); state['optimizer'][field] = {}
    with pytest.raises(FalValidationError): validate_cloud_state_json(state)
    result = run_shared('try { validateCloudPromptHistory(' + json.dumps(state['optimizer']) + '); } catch(e) { console.log(e.message); }')
    assert 'Invalid Cloud optimizer history/state fields' in result.stdout


def test_history_size_limit_no_truncation_and_text_not_secret_scanned(monkeypatch):
    state = previous(); state['optimizer']['original_prompt'] = '中' * 90000
    with pytest.raises(FalValidationError, match='256 KiB'): validate_cloud_state_json(state)
    result = run_shared('try { validateCloudPromptHistory(' + json.dumps(state['optimizer']) + '); } catch(e) { console.log(e.message); }')
    assert '256 KiB' in result.stdout
    failed = run_panel(state=previous(), config=config_response_from_actual_handler(monkeypatch), runtime=True,
                       optimizedPrompt='x' * 270000)
    assert pair(failed['state']) == pair(previous())
    assert failed['state']['prompt'] == previous()['prompt']
    assert any('256 KiB' in alert for alert in failed['alerts'])
    state['optimizer']['original_prompt'] = 'User text may literally say api_key or contain private information.'
    validate_cloud_state_json(state)
