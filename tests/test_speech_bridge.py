import copy
import importlib
import json
import sys
import types
from pathlib import Path
import pytest
import torch

from hutx_minimax_h3_testpkg.speech_bridge import fit_duration,bridge_audio,verify_locked_bundle
from hutx_minimax_h3_testpkg.speech_service import SpeechService,decode_wav
from hutx_minimax_h3_testpkg.speech_validation import PCM,SpeechError,validate_request,fingerprint
from hutx_minimax_h3_testpkg.speech_snapshot import load_snapshot
from tests.test_local_video_core import local_module,config,legacy_namespace


def length(seconds):
    frames=round(seconds*24)
    return frames+(5-frames%17)%17


def audio(seconds=5,rate=16000):
    return {'waveform':torch.full((1,1,round(seconds*rate)),0.1),'sample_rate':rate}


def state(mode='text_keyframes',**media):
    return {'schema_version':1,'mode':mode,'prompt':'<Picture 1> 说话。',
            'media':[[slot,{'name':name,'kind':'audio' if 'audio' in slot else 'video' if 'video' in slot else 'image'}] for slot,name in media.items()]}


@pytest.fixture
def bridge_env(tmp_path,monkeypatch):
    folder=types.ModuleType('folder_paths');folder.get_input_directory=lambda:str(tmp_path)
    monkeypatch.setitem(sys.modules,'folder_paths',folder)
    return tmp_path


@pytest.mark.parametrize('seconds,requested,expected',[(.2,2,4),(4,4,4),(5.15,5,5),(5.4,5,6),(14.375,4,14)])
def test_duration_exact_sample_budget(seconds,requested,expected):
    selected,frames=fit_duration(round(seconds*24000),24000,requested,length)
    assert selected==expected and frames<=360 and frames/24>=seconds


@pytest.mark.parametrize('seconds',[14.375+1/24000,14.99,15,15.01,20])
def test_boundary_rejects_no_truncation(seconds):
    with pytest.raises(ValueError,match='不会自动截断'):fit_duration(round(seconds*24000),24000,4,length)


def test_requested_fifteen_rejected_even_for_short_speech():
    with pytest.raises(ValueError):fit_duration(16000,16000,15,length)


@pytest.mark.parametrize('frames,task',[
    ({'first_frame':'first.png'},'i2va'),
    ({'last_frame':'last.png'},'l2va'),
    ({'first_frame':'first.png','last_frame':'last.png'},'fl2va'),
])
def test_keyframe_bridge_preserves_prompt_and_original_state(bridge_env,frames,task):
    original=state(**frames);before=copy.deepcopy(original)
    updated,seconds,ordinal,report=bridge_audio(original,task,audio(5.4),5,'FL2VA','reject_conflicts','auto',length)
    assert original==before and updated['prompt']==original['prompt']
    assert dict(updated['media'])['hybrid_audio']['name']==report['audio_file']
    assert seconds==6 and ordinal==1 and not report['truncated']
    assert decode_wav((bridge_env/report['audio_file']).read_bytes()).seconds==5.4


def test_ref_video_soundtrack_and_sparse_audio_ordinal(bridge_env):
    original=state('all_reference',ref_image_3='face.png',ref_video_2='clip.mp4',ref_audio_1='old.wav')
    original['prompt']='<Picture 1> <Video 1> <Audio 1> <Audio 2>'
    with pytest.raises(ValueError,match='已有参考音频'):
        bridge_audio(original,'ref2va',audio(),5,'Ref2VA','reject_conflicts','auto',length,lambda n:{'has_audio':True})
    updated,_,ordinal,report=bridge_audio(original,'ref2va',audio(),5,'Ref2VA','use_connected_audio','auto',length,lambda n:{'has_audio':True})
    assert ordinal==3 and report['slot']=='ref_audio_2' and report['label']=='<Audio 3>'
    assert updated['prompt']==original['prompt'] and updated['media'][:-1]==original['media']


def test_muted_video_not_counted(bridge_env):
    original=state('all_reference',ref_video_3='clip.mp4');original['media'][0][1]['muted']=True
    updated,_,ordinal,_=bridge_audio(original,'ref2va',audio(),5,'Ref2VA','reject_conflicts','auto',length,
        lambda n:pytest.fail('Muted video must not be probed for drive audio'))
    assert ordinal==1 and updated['media'][0][1]['muted']


def test_sparse_append_cannot_renumber_existing_audio(bridge_env):
    original=state('all_reference',ref_image_1='face.png',ref_audio_3='old.wav')
    with pytest.raises(ValueError,match='末尾追加'):bridge_audio(original,'ref2va',audio(),5,'Ref2VA','use_connected_audio','auto',length)
    with pytest.raises(ValueError,match='改变现有音频编号'):bridge_audio(original,'ref2va',audio(),5,'Ref2VA','use_connected_audio','ref_audio_1',length)
    updated,_,ordinal,report=bridge_audio(original,'ref2va',audio(),5,'Ref2VA','use_connected_audio','ref_audio_3',length)
    assert ordinal==1 and report['replaced_slot']=='ref_audio_3' and len(updated['media'])==2


def test_conflict_requires_explicit_replacement_and_drops_old_trim(bridge_env):
    original=state(first_frame='face.png',hybrid_audio='old.wav');original['media'][1][1].update(trimStart=3,trimEnd=4)
    with pytest.raises(ValueError,match='已有 Hybrid'):bridge_audio(original,'i2va',audio(),5,'FL2VA','reject_conflicts','auto',length)
    updated,_,_,_=bridge_audio(original,'i2va',audio(),5,'FL2VA','use_connected_audio','auto',length)
    assert set(dict(updated['media'])['hybrid_audio'])=={'name','kind'}
    assert original['media'][1][1]['trimStart']==3


@pytest.mark.parametrize('task,family',[('t2va','FL2VA'),('ref2va','FL2VA'),('i2va','unconfirmed')])
def test_unverified_or_wrong_modes_fail_before_writing(bridge_env,task,family):
    with pytest.raises(ValueError):bridge_audio(state(first_frame='a.png'),task,audio(),5,family,'reject_conflicts','auto',length)
    assert not list(bridge_env.rglob('*.wav'))


@pytest.mark.parametrize('value',[float('nan'),float('inf'),1.1])
def test_invalid_amplitude_not_clipped(bridge_env,value):
    data=audio();data['waveform'][0,0,0]=value
    with pytest.raises(ValueError):bridge_audio(state(first_frame='a.png'),'i2va',data,5,'FL2VA','reject_conflicts','auto',length)


def test_pcm_file_deduplicated_and_failed_fit_leaves_audio_intact(bridge_env):
    args=(state(first_frame='a.png'),'i2va',audio(),5,'FL2VA','reject_conflicts','auto',length)
    first=bridge_audio(*args)[3];second=bridge_audio(*args)[3]
    assert first['audio_file']==second['audio_file'] and len(list(bridge_env.rglob('*.wav')))==1
    with pytest.raises(ValueError):bridge_audio(args[0],'i2va',audio(15),5,'FL2VA','reject_conflicts','auto',length)
    assert (bridge_env/first['audio_file']).exists()


def test_expansion_routes_new_audio_without_altering_output_contract(local_module,tmp_path,monkeypatch):
    local_module.folder_paths.get_input_directory=lambda:str(tmp_path)
    fake=types.ModuleType('hutx_minimax_h3_testpkg.nodes');fake.calculate_length=length
    monkeypatch.setitem(sys.modules,fake.__name__,fake)
    result=local_module.GHLocalVideoInputGH.execute(**config(first_frame='face.png'),driver_audio=audio(5.4),driver_model_family='FL2VA')
    inputs=result.expand['1']['inputs'];report=json.loads(result.expand['2']['inputs']['configuration'])
    assert inputs['duration_seconds']==6 and inputs['drive_audio_ordinal']==1 and inputs['audio_mode']=='lock_source'
    assert inputs['audio_denoise_strength']==0 and inputs['hybrid_audio'].endswith('.wav')
    assert report['requested_seconds']==5 and report['driver_audio']['source_seconds']==5.4
    assert len(result.args)==3


def test_post_conditioning_mismatch_blocked_before_sampler(bridge_env,monkeypatch):
    _,_,_,report=bridge_audio(state(first_frame='face.png'),'i2va',audio(),5,'FL2VA','reject_conflicts','auto',length)
    pcm=decode_wav((bridge_env/report['audio_file']).read_bytes())
    data=torch.frombuffer(bytearray(pcm.data),dtype=torch.int16).float().reshape(1,1,-1)/32768
    source={'waveform':data,'sample_rate':pcm.sample_rate}
    fake=types.ModuleType('hutx_minimax_h3_testpkg.nodes');fake._load_audio_file=lambda n:source
    monkeypatch.setitem(sys.modules,fake.__name__,fake)
    bundle={'mux_audio':source,'length':report['frame_count'],'is_original_audio':True}
    verify_locked_bundle(bundle,report)
    bundle['mux_audio']={'waveform':data*.5,'sample_rate':pcm.sample_rate}
    with pytest.raises(ValueError,match='驱动源'):verify_locked_bundle(bundle,report)


def test_snapshot_survives_cache_expiry_and_rejects_changed_parameters(bridge_env):
    params={'engine':'local','mode':'preset','voice':'local:demo-a','mock_demo':True,'text':'旧路径独立测试'}
    service=SpeechService();result,_=service.generate(params);saved=service.adopt(result.audio_id)
    service.cache.clear()
    expected=fingerprint(validate_request(params),None)
    restored=load_snapshot(saved,expected)
    assert restored.pcm==result.pcm and saved.endswith('.json')
    with pytest.raises(SpeechError,match='未自动重新调用 TTS'):load_snapshot(saved,fingerprint(validate_request(dict(params,text='新台词')),None))
    assert all('api_key' not in p.read_text(encoding='utf-8') for p in bridge_env.rglob('*.json'))


def test_snapshot_tampering_rejected(bridge_env):
    params={'engine':'local','mode':'preset','voice':'local:demo-a','mock_demo':True,'text':'测试'}
    service=SpeechService();result,_=service.generate(params);saved=service.adopt(result.audio_id)
    (bridge_env/saved).write_text('{}')
    with pytest.raises(SpeechError):load_snapshot(saved,result.input_fingerprint)


def test_adopt_route_accepts_only_audio_id_and_no_secret(bridge_env,monkeypatch):
    import asyncio
    from hutx_minimax_h3_testpkg import speech_routes as routes
    service=SpeechService();result,_=service.generate({'engine':'local','mode':'preset','voice':'local:demo-a','mock_demo':True,'text':'路由测试'})
    monkeypatch.setattr(routes,'SPEECH_SERVICE',service)
    class Request:
        def __init__(self,data):self.data=data
        async def json(self):return self.data
    async def run():
        response=await routes.speech_adopt(Request({'audio_id':result.audio_id}))
        assert response.status==200 and set(json.loads(response.body))=={'adopted_audio_file'}
        response=await routes.speech_adopt(Request({'audio_id':result.audio_id,'api_key':'TEST_SECRET'}))
        assert response.status==400 and b'TEST_SECRET' not in response.body
    asyncio.run(run())


def test_explicit_user_crop_changes_actual_checked_length(bridge_env):
    long_audio=audio(20)
    # A user-selected slice (e.g. ComfyUI TrimAudioDuration) is the input contract.
    selected={'waveform':long_audio['waveform'][...,16000:16000*6],'sample_rate':16000}
    _,_,_,report=bridge_audio(state(first_frame='a.png'),'i2va',selected,5,'FL2VA','reject_conflicts','auto',length)
    assert report['source_seconds']==5 and not report['truncated']


def test_adopted_node_retry_never_calls_tts(bridge_env,monkeypatch):
    params={'engine':'local','mode':'preset','voice':'local:demo-a','mock_demo':True,'text':'再次执行'}
    service=SpeechService();result,_=service.generate(params);saved=service.adopt(result.audio_id)
    from tests.test_local_video_core import Output
    monkeypatch.setitem(sys.modules,'comfy_api.latest',types.SimpleNamespace(io=types.SimpleNamespace(ComfyNode=object,NodeOutput=Output)))
    name='hutx_minimax_h3_testpkg.speech_nodes';monkeypatch.delitem(sys.modules,name,raising=False)
    nodes=importlib.import_module(name)
    monkeypatch.setattr(nodes,'SPEECH_SERVICE',types.SimpleNamespace(generate=lambda *a:pytest.fail('Adopted retry must not call TTS')))
    output=nodes.GHSpeechInputGH.execute(**params,adopted_audio_file=saved)
    assert output.args[1]==result.pcm.seconds
    assert nodes.GHSpeechInputGH.fingerprint_inputs(**params,adopted_audio_file=saved)
    with pytest.raises(SpeechError):nodes.GHSpeechInputGH.execute(**dict(params,text='变化'),adopted_audio_file=saved)
    metadata=json.loads((bridge_env/saved).read_text(encoding='utf-8'))
    (bridge_env/metadata['audio']).write_bytes(b'corrupt')
    with pytest.raises(SpeechError):nodes.GHSpeechInputGH.execute(**params,adopted_audio_file=saved)


def test_real_legacy_executor_selects_new_audio_after_video_track(bridge_env):
    original=state('all_reference',ref_image_1='face.png',ref_video_1='film.mp4',ref_audio_1='old.wav')
    updated,seconds,ordinal,report=bridge_audio(original,'ref2va',audio(),5,'Ref2VA','use_connected_audio','auto',length,lambda n:{'has_audio':True})
    ns=legacy_namespace();called={}
    class Loader:
        def load_clip(self,*args):return ('clip',)
        def load_vae(self,*args):return ('vae',)
    def conditioning(*args):
        called['args']=args
        return ('positive',{},args[14],args[3],'{}','ref2va')
    def loaded_audio(name):
        return {'source':name,'waveform':torch.zeros((1,1,1)),'sample_rate':1} if name else None
    ns.update(_load_image_file=lambda n:types.SimpleNamespace(shape=(1,640,960,3)) if n else None,
        _load_video_frames=lambda n,l:(types.SimpleNamespace(shape=(124,640,960,3)),loaded_audio('video')) if n else (None,None),
        _load_audio_file=loaded_audio,
        _trim_audio_to_duration=lambda a,s:a,_clip_audio_to_duration=lambda a,s:a,_apply_audio_selection=lambda a,s:a,
        align_frame_count_down=lambda n:n-((n-5)%17),nodes=types.SimpleNamespace(CLIPLoader=Loader,VAELoader=Loader),
        build_conditioning=conditioning,_release_text_encoder=lambda c:None,build_source_manifest=lambda **kw:{},
        folder_paths=types.SimpleNamespace(get_input_directory=lambda:str(bridge_env)))
    from hutx_minimax_h3_testpkg.local_video_state import MEDIA_SLOTS
    media={slot:'' for slot in MEDIA_SLOTS}
    media.update({s:e['name'] for s,e in updated['media']})
    bundle=ns['MiniMaxH3IntegrationGH'].execute(clip_name='clip',video_vae_name='video',audio_vae_name='audio',
        main_mode='all_reference',prompt=original['prompt'],aspect='16:9',megapixels=.5,duration_seconds=seconds,
        audio_mode='lock_source',drive_audio_ordinal=ordinal,task_type='auto',audio_denoise_strength=0,
        strict_prompt_tags=True,ref_image_size='match',**media)[0]
    assert ordinal==3 and called['args'][13]['source']==report['audio_file']
    assert bundle['mux_audio']['source']==report['audio_file'] and bundle['is_original_audio']
