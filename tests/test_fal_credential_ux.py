import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from hutx_minimax_h3_testpkg import fal_credentials as creds
from .test_fal_credentials import store, KEY, Request

COMBINATIONS=[(False,False,False,'none'),(False,True,False,'session'),(False,False,True,'persisted'),
              (True,False,False,'environment'),(False,True,True,'session'),(True,True,True,'environment')]
FIELDS={'configured','active_source','environment_configured','session_configured','persisted_configured','persistence_supported'}


@pytest.mark.parametrize('env,session,persisted,source',COMBINATIONS)
def test_status_independent_flags_and_priority(env,session,persisted,source,store,monkeypatch):
    if session: store.save(KEY+'_session','session')
    if persisted: store.save(KEY+'_persisted')  # Saving to disk must preserve an existing session.
    if env: monkeypatch.setenv('FAL_KEY',KEY+'_env')
    status=store.status()
    assert set(status)==FIELDS
    assert status==dict(configured=source!='none',active_source=source,environment_configured=env,
                       session_configured=session,persisted_configured=persisted,persistence_supported=True)
    response=asyncio.run(creds.fal_credential_get(Request()))
    assert json.loads(response.text)==status
    assert KEY not in response.text and 'encrypted_blob' not in response.text
    if source!='none':
        assert store.resolve()[1]==source
    store.delete_persisted()
    expected='environment' if env else 'session' if session else 'none'
    assert store.status()['active_source']==expected
    assert not store.status()['persisted_configured']


def ui(**kwargs):
    result=subprocess.run([shutil.which('node'),str(Path(__file__).with_name('frontend_fal_credentials_fixture.mjs'))],
                          input=json.dumps(kwargs),encoding='utf-8',capture_output=True,check=True,timeout=20)
    return json.loads(result.stdout)


@pytest.mark.parametrize('env,session,persisted,source',COMBINATIONS)
def test_ui_combined_sources_placeholders_and_safe_status(env,session,persisted,source):
    data=ui(environment=env,initialSession=session,initialPersisted=persisted,actions=[],echo=True)
    status=data['initial']
    assert status['active']=={'none':'当前生效： ○ 未配置','session':'当前生效： ● 本次会话',
                             'persisted':'当前生效： ● 本机安全存储','environment':'当前生效： ● 环境变量 FAL_KEY'}[source]
    assert status['session']=='会话凭证： '+('✓ 已配置' if session else '○ 未配置')
    assert status['persisted']=='本机凭证： '+('✓ Windows DPAPI 已保存' if persisted else '○ 未保存')
    expected='环境变量已配置，可输入临时凭证但当前不会优先使用' if env else '输入新的 FAL_KEY 以替换会话凭证' if session else '输入新的 FAL_KEY 以更新本机凭证' if persisted else '输入 FAL_KEY'
    assert status['placeholder']==expected
    assert KEY not in json.dumps(status)
    assert data['serialized']=={'properties':{'legacy':True},'widgets_values':['dry_run']}


@pytest.mark.parametrize('action',['session','save'])
def test_empty_input_red_error_no_save_request_and_clear_on_edit(action):
    data=ui(actions=[{'type':action},{'type':'input','value':'TEST_FAL_KEY'}])
    assert data['states'][0]['feedback']=='✕ 请先输入 FAL_KEY'
    assert data['states'][0]['kind']=='error'
    assert not data['states'][0]['feedbackHidden']
    assert data['states'][1]['feedbackHidden']
    assert not any(r['method']=='POST' for r in data['requests'])


@pytest.mark.parametrize('action,session,env,kind,text',[
    ('session',False,False,'success','ComfyUI 重启后失效'),
    ('save',False,False,'success','ComfyUI 重启后仍可使用'),
    ('save',True,False,'warning','当前仍由本次会话凭证生效'),
    ('save',False,True,'warning','当前仍由环境变量 FAL_KEY 生效'),
    ('session',False,True,'warning','但当前仍由环境变量 FAL_KEY 生效'),
])
def test_save_feedback_and_busy_state(action,session,env,kind,text):
    data=ui(initialSession=session,environment=env,actions=[{'type':'input','value':KEY},{'type':action}],echo=True)
    final=data['states'][-1]
    assert final['kind']==kind and text in final['feedback']
    assert final['key']=='' and not final['disabled'] and not final['feedbackHidden']
    pending=data['pendingStates'][0]
    assert pending['disabled'] and pending['feedback']=='● 正在安全保存...' and pending['key']==''
    assert KEY not in final['feedback'] and KEY not in json.dumps(data['serialized'])
    assert len([r for r in data['requests'] if r['method']=='POST'])==1
    assert data['errors']==[]


@pytest.mark.parametrize('env,session',[(False,False),(False,True),(True,True)])
def test_delete_confirmation_and_fallback(env,session):
    data=ui(initialPersisted=True,initialSession=session,environment=env,
            actions=[{'type':'delete'},{'type':'cancel-delete'},{'type':'delete'},{'type':'confirm-delete'}])
    assert not data['states'][0]['confirmHidden']
    assert data['states'][1]['confirmHidden']
    final=data['states'][-1]
    assert final['feedback']=='✓ 已删除本机安全凭证' and final['kind']=='success'
    assert final['persisted']=='本机凭证： ○ 未保存'
    assert final['active']==('当前生效： ● 环境变量 FAL_KEY' if env else '当前生效： ● 本次会话' if session else '当前生效： ○ 未配置')
    assert len([r for r in data['requests'] if r['method']=='DELETE'])==1


def test_delete_absent_info_without_network_delete():
    data=ui(initialSession=True,actions=[{'type':'delete'}])
    assert data['states'][0]['kind']=='info'
    assert data['states'][0]['feedback']=='当前没有本机安全凭证可删除。'
    assert not any(r['method']=='DELETE' for r in data['requests'])


def test_duplicate_save_is_ignored_and_failure_feedback_is_secret_free():
    data=ui(actions=[{'type':'input','value':KEY},{'type':'save-double'}])
    assert len([r for r in data['requests'] if r['method']=='POST'])==1
    failed=ui(fail=True,echo=True,actions=[{'type':'input','value':KEY},{'type':'save'}])
    assert failed['states'][-1]['kind']=='error'
    assert not failed['states'][-1]['feedbackHidden']
    assert KEY not in failed['states'][-1]['feedback']
