import importlib
import json
import sys
import types
import pytest
from tests.test_local_video_core import local_module, config
from tests.test_speech_bridge import bridge_env, state, audio, length
from hutx_minimax_h3_testpkg.speech_service import SpeechService
from hutx_minimax_h3_testpkg.speech_validation import SpeechError
from hutx_minimax_h3_testpkg.multi_speech_bridge import bridge_references


@pytest.fixture
def multi(local_module):
    return importlib.import_module('hutx_minimax_h3_testpkg.multi_speech_nodes')


def saved_role(text, service):
    parameters={'engine':'local','mode':'preset','voice':'local:demo-a','mock_demo':True,'text':text}
    result,_=service.generate(parameters)
    return json.dumps({**parameters,'adopted_audio_file':service.adopt(result.audio_id),'name':'同名角色'})


def test_three_snapshots_reuse_without_generation(multi,bridge_env,monkeypatch):
    service=SpeechService()
    roles=[saved_role(text,service) for text in ['甲','乙乙','丙丙丙']]
    service.cache.clear()
    monkeypatch.setattr(SpeechService,'generate',lambda *a,**k:pytest.fail('Queue must not synthesize'))
    result=multi.GHMultiSpeechInputGH.execute(*roles)
    assert len(result.args)==4
    report=json.loads(result.args[3])
    assert [r['role'] for r in report]==list('ABC')
    assert all(r['configured'] for r in report)
    assert not any(k in result.args[3] for k in ['adopted_audio_file','reference_file','key','credential'])
    assert len(multi.GHMultiSpeechInputGH.fingerprint_inputs(*roles))==3


def test_unused_role_and_stale_or_missing_adoption(multi,bridge_env):
    assert multi.GHMultiSpeechInputGH.execute().args[:3]==(None,None,None)
    assert multi.adopted_role('{"enabled":false,"text":"unused"}','B') is None
    with pytest.raises(SpeechError,match='采用'):multi.adopted_role('{"text":"未采用"}','A')
    raw=json.loads(saved_role('原台词',SpeechService()));raw['text']='changed'
    with pytest.raises(SpeechError):multi.adopted_role(json.dumps(raw),'B')


@pytest.mark.parametrize('field',['api_key','apiKey','credential_ref','key','secret'])
def test_role_rejects_secret_fields(multi,field):
    with pytest.raises(SpeechError) as error:multi.read_role(json.dumps({field:'TEST_SECRET'}))
    assert 'TEST_SECRET' not in str(error.value)


def test_three_fixed_slots_and_unmodified_state(multi,bridge_env):
    original=state('all_reference',ref_image_1='face.png')
    updated,report=bridge_references(original,'ref2va',[audio(1),audio(2),audio(3)],4,length)
    assert [s for s,_ in updated['media'] if s.startswith('ref_audio')]==['ref_audio_1','ref_audio_2','ref_audio_3']
    assert len(original['media'])==1
    assert report['audio_mode']=='reference_only'
    sparse,_=bridge_references(original,'ref2va',[None,None,audio(1)],4,length)
    assert 'ref_audio_3' in dict(sparse['media']) and 'ref_audio_1' not in dict(sparse['media'])


def test_role_audio_uses_real_duration_and_temporarily_mutes_video_soundtrack(bridge_env):
    original=state('all_reference',ref_video_1='clip.mp4')
    updated,report=bridge_references(original,'ref2va',[audio(2),audio(3),audio(4)],9,length)
    entries=dict(updated['media'])
    assert entries['ref_video_1']['muted'] is True
    assert dict(original['media'])['ref_video_1'].get('muted') is None
    assert report['durations_seconds']==[2,3,4]
    assert report['muted_reference_video_audio_slots']==['ref_video_1']


@pytest.mark.parametrize('kwargs,match',[
    ({'task':'i2va'},'全能参考'),
    ({'requested':10,'audios':[audio(6)]*3},'累计超过'),
    ({'audios':[audio(8),None,None]},'不会截断'),
    ({'state':state('all_reference',ref_image_1='face.png',ref_audio_1='existing.wav')},'不会自动覆盖'),
])
def test_reference_limits_and_conflicts(multi,bridge_env,kwargs,match):
    parameters=dict(state=state('all_reference',ref_image_1='face.png'),task='ref2va',audios=[audio(1)]*3,requested=4,calculate_length=length)
    with pytest.raises(ValueError,match=match):bridge_references(**(parameters|kwargs))


def test_local_expansion_uses_reference_only_and_keeps_legacy(local_module,multi,bridge_env,monkeypatch):
    # Only the graph assembly is run; no model, TTS, video or API invocation.
    import folder_paths
    folder_paths.get_filename_list=lambda name: {'diffusion_models':['h3.safetensors'],'text_encoders':['clip.safetensors'],'vae':['video.safetensors','audio.safetensors']}[name]
    fake=types.ModuleType('hutx_minimax_h3_testpkg.nodes');fake.calculate_length=length
    monkeypatch.setitem(sys.modules,'hutx_minimax_h3_testpkg.nodes',fake)
    args=config(main_mode='all_reference',ref_image_1='face.png',duration_seconds=4)
    result=local_module.GHLocalVideoInputGH.execute(**args,reference_audio_1=audio(1),reference_audio_2=audio(2),reference_audio_3=audio(3))
    payload=result.expand['1']['inputs']
    assert payload['audio_mode']=='reference_only'
    assert all(payload[f'ref_audio_{i}'].startswith('hutx-speech/roles/') for i in (1,2,3))
    assert local_module.GHLocalVideoInputGH.execute(**args).expand['1']['inputs']['audio_mode']=='lock_source'
    combined=local_module.GHLocalVideoInputGH.execute(**args,reference_audio_1=audio(1),driver_audio=audio(1))
    assert combined.expand['1']['inputs']['audio_mode']=='reference_only'
    # In text/keyframe mode, connected role references are inactive and the
    # established driver_audio branch remains the lock-source path.
    keyframe=config(main_mode='text_keyframes',first_frame='face.png',duration_seconds=4,
                    driver_model_family='FL2VA')
    driven=local_module.GHLocalVideoInputGH.execute(**keyframe,reference_audio_1=audio(1),driver_audio=audio(1))
    assert driven.expand['1']['inputs']['audio_mode']=='lock_source'
    assert json.loads(driven.expand['2']['inputs']['configuration'])['driver_audio']['slot']=='hybrid_audio'
