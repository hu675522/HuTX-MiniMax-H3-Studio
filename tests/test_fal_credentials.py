from __future__ import annotations

import asyncio
import base64
import importlib
import json
import logging
import os
import sys
import traceback
import types

import pytest

from hutx_minimax_h3_testpkg import fal_credentials as creds
from hutx_minimax_h3_testpkg.fal_api_client import FalApiClient

KEY = 'TEST_FAL_KEY'


class MockCipher:
    supported = True
    def encrypt(self, data): return bytes(x ^ 0xA7 for x in data)
    def decrypt(self, data): return self.encrypt(data)


@pytest.fixture
def store(tmp_path, monkeypatch):
    value = creds.FalCredentialStore(tmp_path / 'fal_credentials.dat', MockCipher())
    monkeypatch.setattr(creds, 'FAL_CREDENTIALS', value)
    return value


def test_priority_session_restart_persisted_and_delete(store, monkeypatch):
    store.save(KEY + '_disk')
    store.save(KEY + '_session', 'session')
    monkeypatch.setenv('FAL_KEY', KEY + '_env')
    assert creds.resolve_fal_api_key() == KEY + '_env'
    assert store.status()['active_source'] == 'environment'
    monkeypatch.delenv('FAL_KEY')
    assert creds.resolve_fal_api_key() == KEY + '_session'
    restart = creds.FalCredentialStore(store.path(), MockCipher())
    assert restart.resolve() == (KEY + '_disk', 'persisted')
    restart.delete_persisted()
    assert not restart.path().exists()
    assert store.resolve() == (KEY + '_session', 'session')
    with pytest.raises(creds.FalCredentialError, match='FAL_KEY'):
        restart.resolve()


def test_delete_does_not_change_environment(store, monkeypatch):
    store.save(KEY)
    monkeypatch.setenv('FAL_KEY', KEY + '_env')
    store.delete_persisted()
    assert os.environ['FAL_KEY'] == KEY + '_env'
    assert store.status()['active_source'] == 'environment'


@pytest.mark.skipif(os.name != 'nt', reason='Windows DPAPI integration')
def test_real_dpapi_current_user_ciphertext_and_restart(tmp_path):
    store = creds.FalCredentialStore(tmp_path / 'fal_credentials.dat')
    store.save(KEY)
    raw = store.path().read_bytes()
    assert KEY.encode() not in raw
    doc = json.loads(raw)
    assert set(doc) == {'version', 'encrypted_blob', 'metadata'}
    assert doc['metadata'] == {'protection': 'DPAPI', 'scope': 'CurrentUser'}
    assert base64.b64decode(doc['encrypted_blob']) != KEY.encode()
    assert creds.FalCredentialStore(store.path()).resolve() == (KEY, 'persisted')


def test_wrong_context_decryption_is_safe(store):
    store.save(KEY)
    class WrongContext(MockCipher):
        def decrypt(self, data): raise RuntimeError(KEY)
    other = creds.FalCredentialStore(store.path(), WrongContext())
    assert other.status()['active_source'] == 'none'
    with pytest.raises(creds.FalCredentialError) as error:
        other.resolve()
    assert KEY not in ''.join(traceback.format_exception(error.value))
    assert '重新配置' in str(error.value)


def test_non_windows_never_writes_plaintext(store, monkeypatch):
    monkeypatch.setattr(creds.WindowsDPAPI, 'supported', property(lambda self: False))
    other = creds.FalCredentialStore(store.path())
    with pytest.raises(creds.FalCredentialError, match='暂不支持'):
        other.save(KEY)
    assert not store.path().exists()
    other.save(KEY, 'session')
    assert other.resolve() == (KEY, 'session')


class Request:
    content_type = 'application/json'
    def __init__(self, data=None): self.data = data
    async def json(self): return dict(self.data)


def test_routes_return_only_status_never_secret(store, monkeypatch):
    async def run():
        saved = await creds.fal_credential_save(Request({'key': KEY, 'storage': 'persisted'}))
        assert saved.status == 200
        for response in [saved, await creds.fal_credential_get(Request())]:
            assert json.loads(response.text)['active_source'] == 'persisted'
            assert KEY not in response.text
            assert response.headers['Cache-Control'] == 'no-store'
        monkeypatch.setenv('FAL_KEY', KEY + '_env')
        deleted = await creds.fal_credential_delete(Request())
        assert json.loads(deleted.text)['active_source'] == 'environment'
        assert not store.path().exists()
    asyncio.run(run())


def test_route_registration_is_idempotent(monkeypatch):
    records = []
    class Routes:
        def __getattr__(self, method):
            return lambda path: lambda fn: records.append((method, path, fn))
    instance = types.SimpleNamespace(routes=Routes())
    monkeypatch.setitem(sys.modules, 'server', types.SimpleNamespace(PromptServer=types.SimpleNamespace(instance=instance)))
    creds.register_fal_credential_routes(); creds.register_fal_credential_routes()
    assert {method for method, _, _ in records} == {'get', 'post', 'delete'}
    assert len(records) == 3
    assert all(path == '/hutx/minimax-h3/fal-credential' for _, path, _ in records)


def test_storage_location_is_comfy_user_default(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, 'folder_paths', types.SimpleNamespace(get_user_directory=lambda: str(tmp_path)))
    assert creds.credential_path() == tmp_path / 'default/HuTX-MiniMax-H3-Studio/fal_credentials.dat'


@pytest.mark.parametrize('stage', ['upload', 'submit', 'wait', 'result'])
def test_sdk_explicit_key_and_provider_errors_redacted(stage, store, monkeypatch, caplog):
    store.save(KEY, 'session')
    def fail():
        logging.getLogger('fal_client.client').warning('Provider error: %s', KEY)
        raise RuntimeError('provider echoed ' + KEY)
    class Handle:
        request_id = 'request-id'
        def get(self):
            if stage == 'wait': fail()
            return {'expanded_prompt': KEY, 'video': {'url':'https://mock/video'}, 'nested':[KEY]}
    class SDK:
        def __init__(self, key): assert key == KEY
        def upload_file(self, path, **options): fail()
        def submit(self, *args, **kwargs):
            if stage == 'submit': fail()
            return Handle()
    module = importlib.import_module('hutx_minimax_h3_testpkg.fal_api_client')
    monkeypatch.setattr(module.importlib, 'import_module', lambda name: types.SimpleNamespace(SyncClient=SDK))
    client = FalApiClient()
    with caplog.at_level(logging.WARNING):
        if stage == 'result':
            result = client.submit_and_wait('mock', {})
            assert KEY not in json.dumps(result.result)
        else:
            with pytest.raises(RuntimeError) as error:
                if stage == 'upload': client.upload_file('mock')
                else: client.submit_and_wait('mock', {})
            assert KEY not in ''.join(traceback.format_exception(error.value))
    assert KEY not in caplog.text


def test_download_failure_report_and_logs_redacted(store, monkeypatch, caplog):
    from hutx_minimax_h3_testpkg import fal_h3_max as service
    from hutx_minimax_h3_testpkg.fal_api_client import FalQueueResult
    from hutx_minimax_h3_testpkg.gh_video_request import normalize_video_request
    from .test_fal_download_fallback import _manifest
    store.save(KEY, 'session')
    class Client:
        def upload_file(self, path): raise AssertionError('T2V has no uploads')
        def submit_and_wait(self, *args, **kwargs):
            return FalQueueResult('mock-id', {'video':{'url':'https://mock/video'}, 'expanded_prompt':KEY})
    monkeypatch.setattr(service, 'FalApiClient', Client)
    def fail(*args): raise RuntimeError(KEY)
    monkeypatch.setattr(service, '_download_video', fail)
    with caplog.at_level(logging.WARNING):
        result = service.FalH3MaxService().run(normalize_video_request({'source_manifest':_manifest()}),
            execution_mode='generate', resolution='480P', prompt_expansion_mode='balanced',seed=-1,enable_safety_checker=True)
    assert KEY not in result.report
    assert KEY not in caplog.text

@pytest.mark.parametrize('session,environment,fail', [(False,False,False),(True,False,False),(False,True,False),(False,False,True)])
def test_frontend_plaintext_only_save_and_old_workflow_serialization(session,environment,fail):
    import subprocess
    import shutil
    from pathlib import Path
    result=subprocess.run([shutil.which('node'),str(Path(__file__).with_name('frontend_fal_credentials_fixture.mjs'))],
        input=json.dumps({'session':session,'environment':environment,'fail':fail}),encoding='utf-8',capture_output=True,check=True)
    data=json.loads(result.stdout)
    assert data['during'] == data['after'] == ''
    posts=[r for r in data['requests'] if r['method']=='POST']
    assert len(posts)==1
    assert posts[0]['body']=={'key':KEY,'storage':'session' if session else 'persisted'}
    assert all(KEY not in json.dumps(r) for r in data['requests'] if r['method']!='POST')
    assert data['serialized']=={'properties':{'legacy':True},'widgets_values':['dry_run']}
    assert KEY not in json.dumps(data['serialized'])
    assert data['errors']==[]
    if not fail:
        assert data['savedStatus']==('当前生效： ● 环境变量 FAL_KEY' if environment else '当前生效： ● 本次会话' if session else '当前生效： ● 本机安全存储')
        assert data['deletedStatus']==('当前生效： ● 环境变量 FAL_KEY' if environment else '当前生效： ● 本次会话' if session else '当前生效： ○ 未配置')
