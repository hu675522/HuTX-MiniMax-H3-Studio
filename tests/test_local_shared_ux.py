import asyncio
import json
import pytest

from .test_local_video_frontend import run
from hutx_minimax_h3_testpkg.local_video_state import local_state, execution_state
from hutx_minimax_h3_testpkg.prompt_optimizer import engine, profiles
from hutx_minimax_h3_testpkg.fal_models import FalValidationError
from .test_local_video_core import local_module, config as core_config


def state(slots=(), mode='text_keyframes', **extra):
    return {'schema_version': 1, 'mode': mode, 'prompt': 'A quiet scene.',
            'media': [[slot, {'name': f'{slot}.png' if 'image' in slot or 'frame' in slot else f'{slot}.mp4' if 'video' in slot else f'{slot}.wav'}] for slot in slots], **extra}


@pytest.mark.parametrize('slots,mode,labels', [
    ([], 'text_keyframes', []),
    (['first_frame'], 'text_keyframes', ['<Picture 1>']),
    (['last_frame'], 'text_keyframes', ['<Picture 1>']),
    (['first_frame','last_frame'], 'text_keyframes', ['<Picture 1>','<Picture 2>']),
    (['last_frame','hybrid_audio'], 'text_keyframes', ['<Picture 1>','<Audio 1>']),
    (['ref_image_3','ref_image_9','ref_video_2','ref_audio_3'], 'all_reference', ['<Picture 3>','<Picture 9>','<Audio 1>','<Video 2>','<Audio 2>']),
])
def test_local_media_adapter_matches_builder_ordinals(slots, mode, labels):
    result=run(state=state(slots, mode), actions=[{'type':'reload'}])
    assert [e['tag'] for e in result['snapshots'][0]['entries']]==labels
    assert local_state(result['state'])==result['state']


@pytest.mark.parametrize('automatic', [False, True])
@pytest.mark.parametrize('profile,resolved', [('auto','structured'),('concise','concise'),('structured','structured')])
def test_manual_auto_profiles_history_and_payload_boundaries(automatic,profile,resolved):
    initial=state(optimizer={'config':{'prompt_profile':profile,'auto_optimize':automatic}})
    result=run(state=initial, actions=[{'type':'auto' if automatic else 'optimize'},{'type':'reload'},{'type':'restore'},{'type':'apply'}])
    assert result['results']==[True]
    assert result['queued']==int(automatic)
    payload=next(r['body'] for r in result['requests'] if r['url'].endswith('/optimize'))
    assert payload['tag_contract']=='local_h3_v1'
    assert 'model_name' not in json.dumps(payload) and 'MODEL_FILE' not in json.dumps(payload)
    assert payload['config']['prompt_profile']==profile
    for snap in result['snapshots']:
        assert snap['state']['optimizer']['original_prompt']=='A quiet scene.'
        assert snap['state']['optimizer']['optimized_prompt']=='Optimized scene.'
    assert result['snapshots'][2]['state']['prompt']=='A quiet scene.'
    assert result['state']['prompt']=='Optimized scene.'
    report=json.loads(result['snapshots'][0]['state']['optimizer']['optimizer_report'])
    assert report['requested_prompt_profile']==profile and report['resolved_prompt_profile']==resolved
    assert report['optimizer_frontend_elapsed_seconds']>=0
    # Fresh JS process simulates browser/ComfyUI restart: no runtime memory survives.
    restarted=run(state=result['state'],actions=[{'type':'restore'},{'type':'apply'}])
    assert restarted['state']==result['state']
    assert not any(r['url'].endswith('/optimize') for r in restarted['requests'])


@pytest.mark.parametrize('during,expected', [('cancel','cancelled'),('edit','cancelled'),('duplicate','success')])
def test_revision_cancel_duplicate_and_queue_guard(during,expected):
    initial=state(optimizer={'config':{'auto_optimize':True},'original_prompt':'Old before','optimized_prompt':'Old after'})
    result=run(state=initial,duringOptimize=during,actions=[{'type':'auto'}])
    assert sum(r['url'].endswith('/optimize') for r in result['requests'])==1
    assert result['snapshots'][0]['timer']==expected
    if during!='duplicate':
        assert result['queued']==0 and isinstance(result['results'][0],str)
        assert result['state']['optimizer']['optimized_prompt']=='Old after'
        if during=='edit':assert result['state']['prompt']=='Edited while waiting'
    else:assert result['queued']==1


def test_failed_optimizer_keeps_history_and_blocks_model_queue():
    initial=state(optimizer={'config':{'auto_optimize':True},'original_prompt':'Before','optimized_prompt':'After'})
    result=run(state=initial,optimizeError='Mock provider rejected request',actions=[{'type':'auto'}])
    assert result['queued']==0
    assert result['snapshots'][0]['timer']=='failure'
    assert result['state']['optimizer']['optimized_prompt']=='After'


@pytest.mark.parametrize('read_media', [False,True])
def test_visual_reads_use_local_active_files_only(read_media):
    initial=state(['last_frame','ref_image_9'],optimizer={'config':{'read_media':read_media}})
    result=run(state=initial,actions=[{'type':'optimize'}])
    payload=next(r['body'] for r in result['requests'] if r['url'].endswith('/optimize'))
    assert payload['task']=='L2VA'
    assert len(payload['media'])==1 and payload['media'][0]['label']=='<Picture 1>'
    assert len(result['visualReads'])==int(read_media)
    assert bool(payload['media'][0].get('images'))==read_media
    assert all('fal' not in r['url'] for r in result['requests'])
    assert 'MOCK_IMAGE' not in json.dumps(result['state'])


@pytest.mark.parametrize('prefix', ['', 'abc','中文','<Video 1>','<Picture 1>','<Audio 1>','，'])
def test_picker_any_boundary_and_consecutive_mentions(prefix):
    result=run(state={**state(['first_frame']), 'prompt':prefix},actions=[{'type':'type','value':'@'},{'type':'key','key':'Enter'},
        {'type':'type','value':'@'},{'type':'key','key':'Enter'}])
    assert result['snapshots'][0]['picker'] is False
    assert result['snapshots'][2]['picker'] is False
    assert result['state']['prompt']==prefix+'<Picture 1><Picture 1>'
    assert result['snapshots'][-1]['caret']==len(result['state']['prompt'])


def test_seven_native_values_and_collapsed_state_survive_reload():
    values={'model_name':'selected.safetensors','clip_name':'clip.safetensors','video_vae_name':'video.safetensors','audio_vae_name':'audio.safetensors','aspect':'9:16','megapixels':0.8,'duration_seconds':12}
    result=run(values=values,actions=[{'type':'collapse'},{'type':'reload'}])
    assert all(dict(result['snapshots'][-1]['widgets'])[k]==v for k,v in values.items())
    assert result['snapshots'][-1]['collapsed'] is True
    execution,_=execution_state(local_state(result['state']))
    assert set(execution)=={'schema_version','mode','prompt','media'}


@pytest.mark.parametrize('bad', [
    {'credential_ref':'ghopt_secret'}, {'api_key':'TEST_SECRET'}, {'config':{'credential_ref':'ghopt_secret'}},
    {'config':{'api_key':'TEST_SECRET'}}, {'config':{'MODEL':{}}}, {'raw_response':{}},
    {'original_prompt':'unpaired'}, {'original_prompt':'x','optimized_prompt':{}},
    {'original_prompt':'x'*262144,'optimized_prompt':'y'}, {'optimizer_report':{}},
])
def test_local_strict_history_rejects_secrets_objects_and_size(bad):
    with pytest.raises((ValueError,FalValidationError)):
        local_state(state(optimizer=bad))


@pytest.mark.parametrize('task,labels', [('T2VA',[]),('I2VA',['<Picture 1>']),('L2VA',['<Picture 1>']),('FL2VA',['<Picture 1>','<Picture 2>']),('Ref2VA',['<Picture 3>','<Video 2>','<Audio 1>'])])
@pytest.mark.parametrize('profile',['auto','concise'])
def test_engine_local_protection_and_profiles(task,labels,profile,monkeypatch):
    # Reuse real shared protection/formatting; the provider is an echo mock.
    payload={'tag_contract':'local_h3_v1','task':task,'prompt':' '.join(labels)+' A quiet scene.', 'media':[{'label':label} for label in labels]}
    async def provider(config,request,**kwargs):
        assert request['context']['resolved_prompt_profile']==('structured' if profile=='auto' else 'concise')
        assert all(label not in request['prompt'] for label in labels)
        return request['prompt']
    monkeypatch.setattr(engine,'request_optimized_prompt',provider)
    output=asyncio.run(engine.optimize_payload({'prompt_profile':profile},payload))
    assert all(label in output for label in labels)
    report=json.loads(engine.optimizer_report(config={'prompt_profile':profile},payload=payload,status='optimized'))
    assert report['requested_prompt_profile']==profile
    assert profiles.resolve_prompt_profile({'prompt_profile':'concise'},{'task':task})==('structured','structured')


def test_metadata_rejects_path_escape_before_open(tmp_path):
    from hutx_minimax_h3_testpkg.local_media_info import inspect_local_media
    for path in ('../outside.mp4','C:/model.safetensors','file [output]'):
        with pytest.raises(ValueError):inspect_local_media(path,tmp_path)


def test_local_save_credential_uses_shared_exchange_and_never_persists_reference():
    result=run(actions=[{'type':'saveCredential'},{'type':'optimize'},{'type':'reload'}])
    assert result['results']==[True]
    secret=[r for r in result['requests'] if r['url'].endswith('/secret')]
    assert len(secret)==1 and 'TEST_SECRET_123' in json.dumps(secret)
    optimize=next(r['body'] for r in result['requests'] if r['url'].endswith('/optimize'))
    assert optimize['config']['credential_ref']=='ghopt_test_xxx'
    assert 'api_key' not in json.dumps(optimize) and 'TEST_SECRET_123' not in json.dumps(optimize)
    for snap in result['snapshots']:
        serialized=json.dumps({k:snap[k] for k in ('state','properties','widgets')})
        assert 'TEST_SECRET_123' not in serialized and 'ghopt_test_xxx' not in serialized and 'credential_ref' not in serialized


def test_comfy_reactive_widget_setter_does_not_reenter_persistence():
    result=run(reactiveWidgets=True,actions=[{'type':'optimize'},{'type':'reload'},{'type':'restore'}])
    assert result['results']==[True]
    assert result['state']['prompt']=='Initial Local prompt'
    assert result['state']['optimizer']['optimized_prompt']=='Optimized scene.'


def test_local_picker_filter_arrows_escape_and_mid_caret():
    initial={**state(['first_frame','last_frame']), 'prompt':'Before After'}
    result=run(state=initial,actions=[{'type':'type','value':'@','caret':7},{'type':'key','key':'ArrowDown'},
        {'type':'key','key':'ArrowUp'},{'type':'key','key':'ArrowDown'},{'type':'key','key':'Enter'}])
    assert result['state']['prompt']=='Before <Picture 2>After'
    assert result['snapshots'][-1]['caret']==18
    escaped=run(state=initial,actions=[{'type':'type','value':'@首','caret':7},{'type':'key','key':'Escape'}])
    assert len(escaped['snapshots'][0]['menu'])==1
    assert escaped['snapshots'][1]['picker'] is True


def test_duplicate_filename_and_deletion_preserve_sparse_picture_identity():
    initial=state(['ref_image_3','ref_image_9'],'all_reference')
    for _,entry in initial['media']:entry['name']='重复 same file.png'
    result=run(state=initial,actions=[{'type':'type','value':'@图片'},{'type':'key','key':'Escape'},{'type':'remove','slot':'ref_image_3'}])
    assert [e['tag'] for e in result['snapshots'][0]['entries']]==['<Picture 3>','<Picture 9>']
    assert [e['tag'] for e in result['snapshots'][-1]['entries']]==['<Picture 9>']


def test_auto_success_state_expands_only_legacy_model_inputs(local_module):
    result=run(state=state(optimizer={'config':{'auto_optimize':True}}),actions=[{'type':'auto'}])
    graph=local_module.GHLocalVideoInputGH.execute(**core_config(gh_local_state_json=json.dumps(result['state']))).expand
    assert graph['0']['inputs']=={'unet_name':'h3.safetensors','weight_dtype':'default'}
    inputs=graph['1']['inputs']
    assert inputs['prompt']=='Optimized scene.'
    assert set(json.loads(inputs['gh_state_json']))=={'schema_version','mode','prompt','media'}
    assert 'optimizer' not in json.dumps(graph) and 'original_prompt' not in json.dumps(graph)


def test_hybrid_payload_preserves_local_template_task():
    result=run(state=state(['last_frame','hybrid_audio']),actions=[{'type':'optimize'}])
    payload=next(r['body'] for r in result['requests'] if r['url'].endswith('/optimize'))
    assert payload['task']=='HYBRID'
    assert [m['label'] for m in payload['media']]==['<Picture 1>','<Audio 1>']


@pytest.mark.parametrize('kind',['missing','unknown','drop'])
def test_local_protection_rejects_invalid_labels(kind,monkeypatch):
    payload={'tag_contract':'local_h3_v1','task':'Ref2VA','prompt':'Use <Picture 3>', 'media':[{'label':'<Picture 3>'}]}
    if kind=='missing':payload['prompt']='No reference'
    if kind=='unknown':payload['prompt']='Use <Picture 9>'
    async def provider(*args,**kwargs):
        if kind!='drop':raise AssertionError('Provider must not run before validation')
        return 'Dropped the reference'
    monkeypatch.setattr(engine,'request_optimized_prompt',provider)
    with pytest.raises(ValueError):asyncio.run(engine.optimize_payload({},payload))
