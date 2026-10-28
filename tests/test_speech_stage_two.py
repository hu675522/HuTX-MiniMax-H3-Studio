from __future__ import annotations

import asyncio
import importlib
import io
import json
import sys
import threading
import types
import wave
from pathlib import Path

import pytest

from hutx_minimax_h3_testpkg.speech_capabilities import video_capabilities
from hutx_minimax_h3_testpkg.speech_service import SpeechService, catalog, wav_bytes, read_reference
from hutx_minimax_h3_testpkg.speech_validation import PCM, SpeechError, SpeechCancelled, validate_request


def params(**extra):
    return dict(engine='local', mode='preset', text='你好，新台词。', voice='local:demo-a', mock_demo=True, **extra)


class Provider:
    def __init__(self): self.calls = []
    def synthesize(self, request, reference, cancel):
        self.calls.append((request, reference))
        return PCM(b'\0\0' * 8000, 16000)


@pytest.mark.parametrize('engine,mode', [('local', 'clone'), ('local', 'preset'), ('cloud', 'clone'), ('cloud', 'preset')])
def test_four_mock_branches(engine, mode):
    provider = Provider(); service = SpeechService(provider)
    request = params(); request.update(engine=engine, mode=mode, voice=engine+':demo-b', reference_text='这是参考原文。')
    reference = PCM(b'\x01\0'*8000, 16000) if mode == 'clone' else None
    result, cached = service.generate(request, reference)
    assert not cached and result.pcm.seconds == .5
    assert provider.calls[0][0]['text'] == '你好，新台词。'
    if mode == 'clone': assert provider.calls[0][1] == reference
    else: assert provider.calls[0][0]['reference_text'] == ''
    assert result.public()['report']['is_mock']


def test_real_engines_fail_closed_no_provider_calls():
    provider = Provider(); service = SpeechService(provider)
    request = params(); request['mock_demo'] = False
    with pytest.raises(SpeechError): service.generate(request)
    assert not provider.calls
    assert not catalog()['real_synthesis_available']


@pytest.mark.parametrize('field,value', [('api_key','TEST_SECRET'),('credential_ref','opaque'),('key','TEST_SECRET'),('runtime',{})])
def test_unknown_secret_fields_rejected(field, value):
    request=params();request[field]=value
    with pytest.raises(SpeechError) as exc: validate_request(request)
    assert 'TEST_SECRET' not in str(exc.value)


@pytest.mark.parametrize('extra', [{'text':''}, {'speed':float('nan')}, {'speed':float('inf')}, {'speed':True},
                                  {'speed':0}, {'revision':-1}, {'mock_demo':'true'}, {'voice':'cloud:demo-a'}])
def test_invalid_fields(extra):
    request=params();request.update(extra)
    with pytest.raises(SpeechError): validate_request(request)


def test_clone_requires_audio_and_allows_automatic_local_transcript():
    request=params();request['mode']='clone'
    with pytest.raises(SpeechError): validate_request(request)
    assert validate_request(request,PCM(b'\0\0'*4,16000))['reference_text']==''
    request['engine']='cloud';assert validate_request(request,PCM(b'\0\0'*4,16000))


@pytest.mark.parametrize('audio',[PCM(b'',16000),PCM(b'1',16000),PCM(b'\0\0',0),PCM(b'\0\0',16000,3)])
def test_invalid_pcm(audio):
    with pytest.raises(SpeechError):audio.validate()


def test_cache_reuse_content_and_parameters():
    p=Provider();s=SpeechService(p)
    request=params();request.update(mode='clone',reference_text='参考原文')
    audio=PCM(b'\0\0'*10,16000)
    first,_=s.generate(request,audio)
    second,cached=s.generate(request,audio)
    assert cached and first.audio_id==second.audio_id and len(p.calls)==1
    s.generate(request,PCM(b'\x01\0'*10,16000))
    s.generate(request,PCM(audio.data,32000))
    for field,value in [('text','新内容'),('reference_text','换参考原文'),('revision',1),('speed',1.1)]:
        changed=dict(request);changed[field]=value;s.generate(changed,audio)
    assert len(p.calls)==7


def test_preview_integer_and_node_float_share_cache():
    p=Provider();s=SpeechService(p);request=params();request['speed']=1
    first,_=s.generate(request);request['speed']=1.0
    second,cached=s.generate(request)
    assert cached and first.audio_id==second.audio_id and len(p.calls)==1


def test_cache_capacity_expiry_and_report_safety():
    s=SpeechService(Provider(),capacity=1)
    first,_=s.generate(params())
    request=params();request['text']='another';s.generate(request)
    with pytest.raises(SpeechError):s.audio(first.audio_id)
    s.ttl=-1
    assert not s.cache or all('api_key' not in json.dumps(r.public()) for _,r in s.cache.values())
    with pytest.raises(SpeechError):s.audio(next(iter(s.cache.values()))[1].audio_id)


def test_inflight_duplicate_cancel_and_retry():
    entered=threading.Event();release=threading.Event();errors=[]
    class Blocking(Provider):
        def synthesize(self,request,reference,cancel):
            entered.set();release.wait(3)
            if cancel.is_set():raise SpeechCancelled()
            return super().synthesize(request,reference,cancel)
    s=SpeechService(Blocking());cancel=threading.Event()
    def run():
        try:s.generate(params(),cancel=cancel)
        except SpeechCancelled:errors.append('cancelled')
    thread=threading.Thread(target=run);thread.start();assert entered.wait(3)
    try:
        with pytest.raises(SpeechError,match='重复'):s.generate(params())
        cancel.set()
    finally:release.set();thread.join(3)
    assert errors==['cancelled'] and not s.cache and not s.inflight
    assert s.generate(params())[0]


def test_provider_exception_never_echoes_secret():
    class Broken:
        def synthesize(self,*args):raise SpeechError('TEST_SECRET_PROVIDER_LEAK')
    with pytest.raises(SpeechError) as exc:SpeechService(Broken()).generate(params())
    assert 'TEST_SECRET' not in str(exc.value)


def test_mock_wave_duration_and_no_real_voice():
    s=SpeechService();request=params();request['text']='测试'
    result,_=s.generate(request)
    with wave.open(io.BytesIO(s.audio(result.audio_id)),'rb') as f:
        assert f.getnframes()/f.getframerate()==result.pcm.seconds==.4
        assert f.getsampwidth()==2 and f.getnchannels()==1
    assert '测试音' in result.public()['report']['notice']


def test_reference_path_guard_and_same_filename_changes(tmp_path,monkeypatch):
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(get_input_directory=lambda:str(tmp_path)))
    for name in ['../escape.wav',str(tmp_path.parent/'escape.wav')]:
        with pytest.raises(SpeechError):read_reference(name)
    path=tmp_path/'中文 参考.wav';path.write_bytes(wav_bytes(PCM(b'\0\0'*10,16000)))
    assert read_reference(path.name).seconds==10/16000
    path.write_bytes(b'invalid')
    with pytest.raises(SpeechError):read_reference(path.name)


def test_capabilities_do_not_promise_unsupported_bridge():
    rows=video_capabilities();assert len(rows)==9
    assert all(row['speech_bridge_enabled']==(row['backend']=='local') and not row['verified_lip_sync'] for row in rows)
    for row in rows:
        if row['backend']=='fal':
            assert row['code_max_seconds']==15 and not row['lock_source_in_code']
            assert bool(row['audio_input']) == (row['mode']=='ref2va' and row['model_family']=='H3 Max')
        else:assert row['code_max_seconds']==30 and row['documented_max_seconds']==15


class Request:
    def __init__(self,data=None,**kwargs):self.data=data;self.__dict__.update(kwargs)
    async def json(self):return self.data


def test_routes_preview_audio_cancel_and_invalid_payload(monkeypatch):
    from hutx_minimax_h3_testpkg import speech_routes as routes
    monkeypatch.setattr(routes,'SPEECH_SERVICE',SpeechService(Provider()))
    async def run():
        response=await routes.speech_generate(Request({'request_id':'a'*32,'parameters':params()}))
        assert response.status==200
        result=json.loads(response.body);assert 'api_key' not in json.dumps(result)
        audio=await routes.speech_audio(Request(match_info={'audio_id':result['audio_id']}))
        assert audio.content_type=='audio/wav'
        bad=await routes.speech_generate(Request({'request_id':'b'*32,'parameters':params(),'api_key':'TEST_SECRET'}))
        assert bad.status==400 and b'TEST_SECRET' not in bad.body
        assert (await routes.speech_audio(Request(match_info={'audio_id':'missing'}))).status==404
        assert (await routes.speech_cancel(Request({'request_id':'missing'}))).status==200
        assert not routes.JOBS
    asyncio.run(run())


def test_route_cancel_running_job_and_reject_duplicate_id(monkeypatch):
    from hutx_minimax_h3_testpkg import speech_routes as routes
    started=threading.Event()
    class Waiter:
        def synthesize(self,request,reference,cancel):
            started.set()
            if cancel.wait(3):raise SpeechCancelled()
            raise AssertionError('cancel not received')
    monkeypatch.setattr(routes,'SPEECH_SERVICE',SpeechService(Waiter()))
    async def run():
        data={'request_id':'c'*32,'parameters':params()}
        task=asyncio.create_task(routes.speech_generate(Request(data)))
        for _ in range(100):
            if started.is_set():break
            await asyncio.sleep(.01)
        assert started.is_set()
        duplicate=await routes.speech_generate(Request(data));assert duplicate.status==400
        assert 'c'*32 in routes.JOBS
        response=await routes.speech_cancel(Request({'request_id':'c'*32}))
        assert json.loads(response.body)['cancelled']
        assert (await task).status==409
        assert not routes.JOBS
    asyncio.run(run())


def test_node_outputs_standard_audio_and_cache(monkeypatch):
    class Output:
        def __init__(self,*args,**kwargs):self.args=args;self.ui=kwargs.get('ui')
    monkeypatch.setitem(sys.modules,'comfy_api.latest',types.SimpleNamespace(io=types.SimpleNamespace(ComfyNode=object,NodeOutput=Output)))
    name='hutx_minimax_h3_testpkg.speech_nodes';monkeypatch.delitem(sys.modules,name,raising=False)
    nodes=importlib.import_module(name);monkeypatch.setattr(nodes,'SPEECH_SERVICE',SpeechService(Provider()))
    result=nodes.GHSpeechInputGH.execute(**params())
    audio,duration,report=result.args
    assert tuple(audio['waveform'].shape)==(1,1,8000) and audio['sample_rate']==16000
    assert duration==.5 and json.loads(report)['is_mock']
    assert json.loads(nodes.GHSpeechInputGH.execute(**params()).args[2])['cache_hit']
