import json
import pytest
from .test_optimizer_persistence import run_panel
from .test_prompt_ux import state
from .test_optimizer_credential_runtime import panel


@pytest.mark.parametrize('value', ['adaptive','21:9','16:9','4:3','1:1','3:4','9:16'])
def test_custom_ratio_round_trip(value):
    result = run_panel(state=state(),locale='zh',uxActions=[{'type':'ratio','value':value}])
    assert result['state']['aspect'] == value
    restored = run_panel(state=result['state'],locale='zh',uxActions=[{'type':'tab','value':'current'}])
    assert restored['ux'][0]['aspect'] == value


@pytest.mark.parametrize('saved,expected', [
    (state(), '自适应 · 默认16:9'),
    (state(first_frame='a.png'), '跟随首帧'),
    (state(first_frame='a.png',last_frame='b.png'), '跟随首帧'),
    (state('all_reference',ref_image_1='a.png'), '自适应'),
])
def test_adaptive_mode_labels(saved, expected):
    result=run_panel(state={**saved,'aspect':'adaptive'},locale='zh',uxActions=[{'type':'tab','value':'current'}])
    assert result['ux'][0]['aspectLabel'] == expected


def test_prompt_history_capture_restore_apply_and_no_new_request_fields(monkeypatch):
    original = 'Use <Picture 1>.'
    optimized = 'Animate <Picture 1> slowly.'
    result = run_panel(runtime=True,locale='zh',config={'mode':'api','provider':'dashscope','read_media':False},
        state={**state(first_frame='a.png'),'prompt':original}, optimizedPrompt=optimized,
        uxActions=[{'type':'tab','value':'compare'}, {'type':'history','value':'restore'},
                   {'type':'tab','value':'optimized'}, {'type':'history','value':'apply'},
                   {'type':'tab','value':'original'}])
    assert result['runtime']['final']['state']['prompt'] == optimized
    assert result['ux'][0]['history'] == [{'title':'Before','text':original,'readOnly':True},{'title':'After','text':optimized,'readOnly':True}]
    assert result['ux'][1]['text'] == original
    assert result['ux'][2]['history'][0]['text'] == optimized
    assert result['ux'][3]['text'] == optimized
    assert result['ux'][4]['history'][0]['text'] == original
    assert result['state']['prompt'] == optimized
    encoded=json.dumps({k:result[k] for k in ('state','properties','widgets_values')})
    for forbidden in ('TEST_SECRET_123','TEST_FAL_KEY','credential_ref','ghopt_test_xxx'):
        assert forbidden not in encoded
    assert len([r for r in result['requests'] if r['url'].endswith('/optimize')]) == 1
    assert not any('fal' in r['url'] for r in result['requests'])
