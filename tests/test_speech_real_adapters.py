import asyncio
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from hutx_minimax_h3_testpkg import speech_local
from hutx_minimax_h3_testpkg.speech_credentials import SpeechCredentials
from hutx_minimax_h3_testpkg.speech_service import SpeechService,wav_bytes,decode_wav
from hutx_minimax_h3_testpkg.speech_validation import PCM,SpeechError,SpeechCancelled
from hutx_minimax_h3_testpkg.speech_providers.bailian import BailianSpeechProvider,endpoint,VOICES

LOCAL_RUN=speech_local.LocalSpeechProvider.synthesize


@pytest.mark.skipif(os.name != 'nt', reason='Windows Current User DPAPI')
def test_speech_real_dpapi_restart_roundtrip(tmp_path):
    path=tmp_path/'speech.dat'
    store=SpeechCredentials(path)
    store.save('TEST_DPAPI_SPEECH_ONLY','persisted')
    assert b'TEST_DPAPI_SPEECH_ONLY' not in path.read_bytes()
    restarted=SpeechCredentials(path)
    assert restarted.persisted()=='TEST_DPAPI_SPEECH_ONLY'
    assert 'TEST_DPAPI' not in json.dumps(restarted.status())
    restarted.delete()
    assert not path.exists()


class Cipher:
    supported=True
    def encrypt(self,data):return bytes(b^0xA5 for b in data)
    def decrypt(self,data):return self.encrypt(data)


def request(**extra):
    data={'engine':'cloud','mode':'preset','text':'你好，这是新台词。','voice':'cloud:longanyang','speed':1.0,
          'mock_demo':False,'revision':0,'cloud_model':'auto','workspace':''}
    data.update(extra);return data


class FakeTransport:
    def __init__(self):self.calls=[]
    def request(self,method,url,**kw):
        self.calls.append((method,url,kw))
        if url.endswith('/uploads'):
            return {'output':dict(upload_dir='temporary',upload_host='https://bucket.oss-cn-beijing.aliyuncs.com',
                oss_access_key_id='TEMP_TEST_ID',signature='TEMP_TEST_SIGNATURE',policy='TEMP_TEST_POLICY',
                x_oss_object_acl='private',x_oss_forbid_overwrite='true')}
        if kw.get('files'):return b''
        if url.endswith('/customization'):return {'output':{'voice_id':'cosyvoice-mock-reference'}}
        if url.endswith('/SpeechSynthesizer'):return {'output':{'audio':{'url':'https://result.oss-cn-beijing.aliyuncs.com/test.wav'}}}
        return wav_bytes(PCM(b'\x01\0'*16000,16000))


@pytest.mark.parametrize('environment,session,persisted,expected',[
    (False,False,False,'none'),(True,False,False,'environment'),(False,True,False,'session'),
    (False,False,True,'persisted'),(False,True,True,'session'),(True,True,True,'environment')])
def test_speech_credential_priority(tmp_path,monkeypatch,environment,session,persisted,expected):
    store=SpeechCredentials(tmp_path/'voice.dat',Cipher())
    if persisted:store.save('TEST_PERSISTED','persisted')
    if session:store.save('TEST_SESSION','session')
    if environment:monkeypatch.setenv('DASHSCOPE_API_KEY','TEST_ENV')
    status=store.status();assert status['active_source']==expected
    assert 'TEST_' not in json.dumps(status)
    if expected=='none':
        with pytest.raises(SpeechError):store.resolve()
    else:assert store.resolve()[1]==expected


def test_encrypted_reload_wrong_context_delete_and_env(tmp_path,monkeypatch):
    path=tmp_path/'voice.dat';store=SpeechCredentials(path,Cipher());store.save('TEST_SPEECH_SECRET','persisted')
    assert b'TEST_SPEECH_SECRET' not in path.read_bytes()
    assert SpeechCredentials(path,Cipher()).resolve()[0]=='TEST_SPEECH_SECRET'
    class Broken(Cipher):
        def decrypt(self,data):raise ValueError('TEST_SPEECH_SECRET')
    broken=SpeechCredentials(path,Broken());assert broken.status()['persisted_unavailable']
    with pytest.raises(SpeechError) as exc:broken.resolve()
    assert 'TEST_' not in str(exc.value)
    store.save('TEST_SESSION','session');monkeypatch.setenv('DASHSCOPE_API_KEY','TEST_ENV');store.delete()
    assert not path.exists() and store.resolve()==('TEST_ENV','environment') and store.session=='TEST_SESSION'


def test_cloud_preset_payload_and_secret_free_audio_download(tmp_path):
    store=SpeechCredentials(tmp_path/'key',Cipher());store.save('TEST_CLOUD_KEY','session')
    transport=FakeTransport();provider=BailianSpeechProvider(transport,store)
    result=provider.synthesize(request(),None,threading.Event());assert result.seconds==1
    call=transport.calls[0];assert call[2]['key']=='TEST_CLOUD_KEY'
    assert call[2]['payload']=={'model':'cosyvoice-v3-flash','input':{'text':'你好，这是新台词。','voice':'longanyang','format':'wav','sample_rate':24000,'speech_rate':1.0}}
    assert 'key' not in transport.calls[-1][2]
    assert not any(c[1].endswith('/uploads') for c in transport.calls)


def test_cloud_multilingual_preset_catalog_and_qwen_payload(tmp_path):
    assert len(VOICES)==20
    groups={voice['group'] for voice in VOICES}
    assert {'中文 · 普通话','中文 · 地方方言','English','日本語','Français','Deutsch','Italiano'}<=groups
    assert len({voice['id'] for voice in VOICES})==20
    store=SpeechCredentials(tmp_path/'key',Cipher());store.save('TEST_CLOUD_KEY','session')
    transport=FakeTransport();provider=BailianSpeechProvider(transport,store)
    provider.synthesize(request(text='Bonjour tout le monde.',voice='cloud:qwen31:longanlingxin_v3.1:fr'),None,threading.Event())
    assert transport.calls[0][2]['payload']=={'model':'qwen-audio-3.1-tts-flash','input':{
        'text':'Bonjour tout le monde.','voice':'longanlingxin_v3.1','format':'wav','sample_rate':24000,
        'rate':1.0,'language_hints':['fr']}}


def test_cloud_dialect_preset_uses_bound_instruction(tmp_path):
    store=SpeechCredentials(tmp_path/'key',Cipher());store.save('TEST_CLOUD_KEY','session')
    transport=FakeTransport();provider=BailianSpeechProvider(transport,store)
    provider.synthesize(request(text='今天我们摆一哈龙门阵。',voice='cloud:cosy:longanhuan_v3:sc'),None,threading.Event())
    payload=transport.calls[0][2]['payload']
    assert payload['model']=='cosyvoice-v3-flash'
    assert payload['input']['voice']=='longanhuan_v3'
    assert payload['input']['instruction']=='请用四川话表达。'


def test_cloud_clone_signed_upload_and_model_bound_reuse(tmp_path):
    store=SpeechCredentials(tmp_path/'key',Cipher());store.save('TEST_CLOUD_KEY','session')
    uploads=[]
    class Upload:
        @contextmanager
        def upload(self,wav,cancel):
            uploads.append(wav);yield 'https://test.oss-cn-beijing.aliyuncs.com/reference.wav?signature=TEST'
    transport=FakeTransport();provider=BailianSpeechProvider(transport,store,Upload())
    audio=PCM(b'\x00\x10\x00\xf0'*8000*10,16000);p=request(mode='clone',voice='',reference_text='参考原文')
    provider.synthesize(p,audio,threading.Event());provider.synthesize(p,audio,threading.Event())
    assert len(uploads)==1 and not any(c[1].endswith('/uploads') for c in transport.calls)
    enrollment=next(c for c in transport.calls if c[1].endswith('/customization'))[2]
    assert enrollment['payload']['input']['url'].startswith('https://test.oss-cn-beijing.aliyuncs.com/')
    assert not enrollment.get('resolve_oss') and enrollment['payload']['input']['target_model']=='cosyvoice-v3.5-plus'
    provider.synthesize(dict(p,cloud_model='cosyvoice-v3.5-flash'),audio,threading.Event())
    store.save('TEST_OTHER_ACCOUNT','session');provider.synthesize(p,audio,threading.Event())
    assert len(uploads)==3


@pytest.mark.parametrize('change',[{'voice':'local:demo-a'},{'cloud_model':'cosyvoice-v3.5-plus'},{'workspace':'evil.com/x'}])
def test_cloud_invalid_combo_no_network(tmp_path,change):
    store=SpeechCredentials(tmp_path/'key',Cipher());store.save('TEST_KEY','session');t=FakeTransport()
    with pytest.raises(SpeechError):BailianSpeechProvider(t,store).synthesize(request(**change),None,threading.Event())
    assert not t.calls


def test_cloud_timeout_no_retry_and_no_secret_report(tmp_path):
    store=SpeechCredentials(tmp_path/'key',Cipher());store.save('TEST_KEY','session')
    class Broken(FakeTransport):
        def request(self,*args,**kw):self.calls.append(args);raise RuntimeError('TEST_KEY in error')
    transport=Broken();provider=BailianSpeechProvider(transport,store)
    s=SpeechService(real_providers={'cloud':provider})
    with pytest.raises(SpeechError) as exc:s.generate(request())
    assert len(transport.calls)==1 and 'TEST_KEY' not in str(exc.value) and not s.cache


def test_real_result_report_cache_and_account_scope(tmp_path):
    store=SpeechCredentials(tmp_path/'key',Cipher());store.save('TEST_KEY','session');t=FakeTransport()
    s=SpeechService(real_providers={'cloud':BailianSpeechProvider(t,store)})
    first,_=s.generate(request());second,cached=s.generate(request())
    assert cached and first.audio_id==second.audio_id and not first.public()['report']['is_mock']
    assert 'TEST_KEY' not in json.dumps(first.public())
    store.save('TEST_NEW_KEY','session');third,cached=s.generate(request());assert not cached and third.audio_id!=first.audio_id


def test_local_preset_bank_and_content_identity(tmp_path):
    audio=PCM(b'\x01\0'*8000,16000)
    a=speech_local.save_voice('我的音色','参考原文',audio)
    b=speech_local.save_voice('重命名','参考原文',audio)
    assert a['id']==b['id'] and len([v for v in speech_local.local_voices() if not v['id'].startswith('local:official-')])==1
    recovered,text=speech_local.preset_reference(a['id']);assert recovered==audio and text=='参考原文'
    with pytest.raises(SpeechError):speech_local.preset_reference('local:../../escape')


@pytest.mark.parametrize('cancelled,failed',[(False,False),(True,False),(False,True)])
def test_local_worker_isolation_cleanup(tmp_path,monkeypatch,cancelled,failed):
    monkeypatch.setattr(speech_local,'local_status',lambda:{'available':True})
    monkeypatch.setattr(speech_local,'runtime_paths',lambda:(tmp_path,tmp_path/'python.exe',tmp_path/'code',tmp_path/'model'))
    monkeypatch.setattr(speech_local,'release_comfy_models',lambda:None)
    monkeypatch.setenv('DASHSCOPE_API_KEY','TEST_SECRET_PROCESS');events=[];folder=[]
    class Process:
        def __init__(self,args,**kw):
            events.append(kw);folder.append(Path(args[-1]));self.returncode=1 if failed else None
            assert not any('TEST_SECRET' in str(x) for x in args) and 'DASHSCOPE_API_KEY' not in kw['env']
            (folder[-1]/'output.wav').write_bytes(wav_bytes(PCM(b'\1\0'*8000,16000)))
        def poll(self):
            if not cancelled and not failed:self.returncode=0
            return self.returncode
        def kill(self):self.returncode=-9;events.append('killed')
        def wait(self,**kw):return self.returncode
    monkeypatch.setattr(speech_local.subprocess,'Popen',Process)
    cancel=threading.Event()
    if cancelled:
        # Set only after launch to exercise terminate-before-temp-cleanup.
        monkeypatch.setattr(cancel,'wait',lambda timeout:True)
    if cancelled or failed:
        with pytest.raises(SpeechError):LOCAL_RUN(speech_local.LocalSpeechProvider(),request(engine='local',reference_text='原文'),PCM(b'\0\x10\0\xf0'*4000,16000),cancel)
    else:assert LOCAL_RUN(speech_local.LocalSpeechProvider(),request(engine='local',reference_text='原文'),PCM(b'\0\x10\0\xf0'*4000,16000),cancel).seconds==.5
    assert folder and not folder[-1].exists() and not speech_local.LOCAL_LOCK.locked()
    if cancelled:assert 'killed' in events


def test_credential_route_only_save_accepts_plaintext(tmp_path,monkeypatch):
    from hutx_minimax_h3_testpkg import speech_routes,speech_credentials
    store=SpeechCredentials(tmp_path/'cred',Cipher());monkeypatch.setattr(speech_credentials,'SPEECH_CREDENTIALS',store)
    class Request:
        method='POST'
        async def json(self):return {'key':'TEST_SAVE_ONLY','storage':'session'}
    response=asyncio.run(speech_routes.speech_credential(Request()))
    assert response.status==200 and b'TEST_SAVE_ONLY' not in response.body and store.resolve()[0]=='TEST_SAVE_ONLY'
