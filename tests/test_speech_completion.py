import ast
import asyncio
import copy
import heapq
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import NamedTuple,Literal,Optional,List
import pytest
from hutx_minimax_h3_testpkg.speech_queue import QueueGate,install_queue_gate
from hutx_minimax_h3_testpkg.speech_quality import check_reference_energy
from hutx_minimax_h3_testpkg.speech_validation import PCM,SpeechCancelled
from hutx_minimax_h3_testpkg.speech_errors import SpeechFailure
from hutx_minimax_h3_testpkg.speech_oss import ReferenceUpload
from hutx_minimax_h3_testpkg.speech_providers.bailian import Transport
TRANSPORT=Transport.request


@pytest.fixture
def host_queue():
    # Exercise the real installed ComfyUI queue class without starting ComfyUI.
    path=Path('D:/AI/ComfyUI/ComfyUI_windows_portable/ComfyUI/execution.py')
    if not path.exists():pytest.skip('Installed ComfyUI fixture unavailable')
    node=next(n for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n,ast.ClassDef) and n.name=='PromptQueue')
    namespace=dict(threading=threading,heapq=heapq,copy=copy,NamedTuple=NamedTuple,Literal=Literal,Optional=Optional,List=List,MAXIMUM_HISTORY_SIZE=100)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),namespace)
    return namespace['PromptQueue'](SimpleNamespace(queue_updated=lambda:None))


def test_preview_blocks_later_queue_dispatch_without_blocking_put(host_queue):
    gate=QueueGate(host_queue);returned=threading.Event();finished=threading.Event()
    def worker():
        _,job=host_queue.get();returned.set();host_queue.task_done(job,{},None);finished.set()
    with gate.preview():
        host_queue.put((0,'test-prompt',{}))
        thread=threading.Thread(target=worker);thread.start()
        assert not returned.wait(.1)
        assert host_queue.get_tasks_remaining()==1
    assert finished.wait(2);thread.join();assert returned.is_set()
    with gate.preview():pass


def test_running_and_pending_queue_reject_preview(host_queue):
    gate=QueueGate(host_queue);host_queue.put((0,'test',{}))
    with pytest.raises(SpeechFailure,match='队列'): 
        with gate.preview():pass
    _,job=host_queue.get()
    with pytest.raises(SpeechFailure,match='队列'):
        with gate.preview():pass
    host_queue.task_done(job,{},None)
    with gate.preview():pass


def test_queue_completion_exception_releases_gate(host_queue):
    def broken(*args,**kwargs):raise RuntimeError()
    host_queue.task_done=broken;gate=QueueGate(host_queue);host_queue.put((0,'test',{}));_,job=host_queue.get()
    with pytest.raises(RuntimeError):host_queue.task_done(job,{},None)
    assert gate.gate.acquire(blocking=False);gate.gate.release()


def test_gate_install_idempotent(host_queue):
    host=SimpleNamespace(prompt_queue=host_queue)
    assert install_queue_gate(host) is install_queue_gate(host)
    assert install_queue_gate(SimpleNamespace()) is None


@pytest.mark.parametrize('data',[b'\0\0'*16000,b'\x01\0'*16000,b'\xff\x7f'*16000],ids=['silence','low_level','dc'])
def test_silence_low_level_and_dc_rejected(data):
    with pytest.raises(SpeechFailure) as exc:check_reference_energy(PCM(data,16000))
    assert exc.value.code=='reference_silent'


class Bucket:
    def __init__(self,fail=''):self.calls=[];self.fail=fail
    def put_object(self,key,data,headers):
        self.calls.append(('put',key,headers))
        if self.fail=='put':raise RuntimeError('TEST_OSS_SECRET')
    def sign_url(self,method,key,expires,slash_safe):
        self.calls.append(('sign',key,expires));return 'https://test.oss-cn-beijing.aliyuncs.com/a?secret=TEST_SIGNATURE'
    def delete_object(self,key):
        self.calls.append(('delete',key))
        if self.fail=='delete':raise RuntimeError('TEST_OSS_SECRET')


@pytest.mark.parametrize('failure',['','registration','cancel','put','delete'])
def test_upload_private_ttl_cleanup_and_redaction(failure):
    bucket=Bucket(failure);upload=ReferenceUpload(lambda:bucket)
    error=None
    try:
        with upload.upload(b'WAV',threading.Event()) as url:
            if failure=='registration':raise SpeechFailure('registration')
            if failure=='cancel':raise SpeechCancelled()
    except Exception as exc:error=exc
    assert bucket.calls[-1][0]=='delete'
    assert bucket.calls[0][2]['x-oss-object-acl']=='private'
    if failure!='put':assert bucket.calls[1][2]==600
    if error:assert 'TEST_' not in str(error)
    assert bool(error)==bool(failure)


@pytest.mark.parametrize('status,expected',[(401,'invalid_credential'),(403,'permission'),(429,'rate_limit'),(500,'provider')])
def test_real_transport_http_errors_safe(monkeypatch,status,expected):
    import requests
    calls=[]
    class Response:
        status_code=status
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,n):yield b'{"message":"TEST_KEY SHOULD NOT ESCAPE"}'
    monkeypatch.setattr(requests,'request',lambda *args,**kwargs:(calls.append(kwargs) or Response()))
    with pytest.raises(SpeechFailure) as exc:TRANSPORT(Transport(),'POST','https://dashscope.aliyuncs.com/api/v1/test',key='TEST_KEY')
    assert exc.value.code==expected and 'TEST_KEY' not in str(exc.value) and len(calls)==1


def test_real_transport_timeout_no_retry(monkeypatch):
    import requests
    calls=[]
    def fail(*args,**kwargs):calls.append(1);raise requests.exceptions.Timeout('TEST_KEY')
    monkeypatch.setattr(requests,'request',fail)
    with pytest.raises(SpeechFailure) as exc:TRANSPORT(Transport(),'POST','https://dashscope.aliyuncs.com/api/v1/test')
    assert exc.value.code=='timeout' and len(calls)==1 and 'TEST_KEY' not in str(exc.value)


def test_route_preserves_only_safe_error_code(monkeypatch):
    from hutx_minimax_h3_testpkg import speech_routes
    class Request:
        async def json(self):return {'request_id':'a'*32,'parameters':{'engine':'cloud','mode':'preset','mock_demo':True}}
    def fail(*args):raise SpeechFailure('rate_limit')
    monkeypatch.setattr(speech_routes,'SPEECH_SERVICE',SimpleNamespace(generate=fail))
    response=asyncio.run(speech_routes.speech_generate(Request()))
    body=json.loads(response.text)
    assert response.status==400 and body['code']=='rate_limit' and '限流' in body['error']
    assert 'a'*32 not in speech_routes.JOBS


def test_oss_child_secrets_only_on_stdin(monkeypatch):
    from hutx_minimax_h3_testpkg import speech_oss
    for name,value in [('HUTX_SPEECH_OSS_ACCESS_KEY_ID','TEST_ID'),('HUTX_SPEECH_OSS_ACCESS_KEY_SECRET','TEST_SECRET')]:
        monkeypatch.setenv(name,value)
    calls=[]
    def run(argv,**kwargs):
        calls.append((argv,kwargs));return SimpleNamespace(returncode=0,stdout=b'{"ok":true}')
    monkeypatch.setattr(speech_oss.subprocess,'run',run)
    speech_oss.IsolatedBucket(Path('python.exe'),'test-bucket').put_object('hutx-speech-temporary/test.wav',b'PCM')
    argv,options=calls[0]
    assert 'TEST_' not in str(argv)
    assert json.loads(options['input'])['access_secret']=='TEST_SECRET'
    assert options['stderr']==speech_oss.subprocess.DEVNULL
