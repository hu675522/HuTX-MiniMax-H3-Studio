from __future__ import annotations

import ast
import importlib
import json
import math
import sys
import types
from pathlib import Path

import pytest

from hutx_minimax_h3_testpkg.local_video_state import local_state, execution_state, MEDIA_SLOTS, media_kind
from hutx_minimax_h3_testpkg.prompt_tags import prepare_prompt, pack_media_tag_ordinals

ROOT = Path(__file__).resolve().parents[1]


class Output:
    def __init__(self, *args, **kwargs): self.args = args; self.expand = kwargs.get('expand')
    def __getitem__(self, i): return self.args[i]


class Graph:
    def __init__(self): self.nodes = {}
    def node(self, kind, **inputs):
        key = str(len(self.nodes)); self.nodes[key] = {'class_type': kind, 'inputs': inputs}
        return types.SimpleNamespace(out=lambda i: [key, i])
    def finalize(self): return self.nodes


@pytest.fixture
def local_module(monkeypatch):
    selections = {'diffusion_models': ['h3.safetensors', 'h3-ref.safetensors'], 'text_encoders': ['clip.safetensors'], 'vae': ['video.safetensors', 'audio.safetensors']}
    folder = types.ModuleType('folder_paths'); folder.get_filename_list = lambda name: selections[name]
    monkeypatch.setitem(sys.modules, 'folder_paths', folder)
    latest = types.ModuleType('comfy_api.latest'); latest.io = types.SimpleNamespace(ComfyNode=object, NodeOutput=Output)
    monkeypatch.setitem(sys.modules, 'comfy_api.latest', latest)
    graph = types.ModuleType('comfy_execution.graph_utils'); graph.GraphBuilder = Graph
    monkeypatch.setitem(sys.modules, 'comfy_execution.graph_utils', graph)
    key = 'hutx_minimax_h3_testpkg.local_video_nodes'; monkeypatch.delitem(sys.modules, key, raising=False)
    return importlib.import_module(key)


def config(**extra):
    return {'model_name': 'h3.safetensors', 'clip_name': 'clip.safetensors', 'video_vae_name': 'video.safetensors',
            'audio_vae_name': 'audio.safetensors', 'aspect': '16:9', 'megapixels': 0.5, 'duration_seconds': 5,
            'prompt': 'A paper boat sails.', **extra}


def legacy_namespace():
    """Run the unchanged production Local executor; mock only loaders/GPU work."""
    tree = ast.parse((ROOT / 'nodes.py').read_text(encoding='utf-8'))
    selected = {'_coerce_int', '_mode_model_number', '_restore_ui_state', '_serialized_first_visual_name',
                '_serialized_muted_video_slots', '_serialized_audio_trim_ranges', '_round32', 'calculate_canvas', 'calculate_length'}
    ns = {'json': json, 'math': math, 'io': types.SimpleNamespace(ComfyNode=object, NodeOutput=Output), 'MAX_RESOLUTION': 16384,
          'DEFAULT_SAMPLER_NAME': 'dual_clock_euler', 'DEFAULT_SCHEDULER_NAME': 'native_flow',
          'ASPECTS': {'adaptive': None, '16:9': 16/9, '21:9': 21/9, '4:3': 4/3, '1:1': 1, '3:4': 3/4, '9:16': 9/16}}
    for item in tree.body:
        if isinstance(item, ast.FunctionDef) and item.name in selected:
            exec(compile(ast.Module(body=[item], type_ignores=[]), 'nodes.py', 'exec'), ns)
        if isinstance(item, ast.ClassDef) and item.name in {'MiniMaxH3IntegrationGH', 'MiniMaxH3IntegrationAdapterGH', 'MiniMaxH3DualClockT8GH', 'MiniMaxH3AVDecodeT8GH'}:
            item.body = [n for n in item.body if isinstance(n, ast.FunctionDef) and n.name == 'execute']
            exec(compile(ast.Module(body=[item], type_ignores=[]), 'nodes.py', 'exec'), ns)
    return ns


@pytest.mark.parametrize('task,media', [('t2va', {}), ('i2va', {'first_frame': 'first.png'}),
    ('l2va', {'last_frame': 'last.png'}), ('fl2va', {'first_frame': 'first.png', 'last_frame': 'last.png'}),
    ('ref2va', {'ref_image_3': '图.png', 'ref_video_2': 'film.mp4', 'ref_audio_1': '音.wav'})])
def test_five_mode_expansion_legacy_preprocessing_adapter_downstream(local_module, task, media):
    result = local_module.GHLocalVideoInputGH.execute(**config(main_mode='all_reference' if task == 'ref2va' else 'text_keyframes', **media))
    graph = result.expand
    assert graph['0'] == {'class_type': 'UNETLoader', 'inputs': {'unet_name': 'h3.safetensors', 'weight_dtype': 'default'}}
    kwargs = graph['1']['inputs']; assert graph['1']['class_type'] == 'MiniMaxH3IntegrationGH'
    assert json.loads(graph['2']['inputs']['configuration'])['task'] == task
    assert kwargs['clip_name'] == 'clip.safetensors' and kwargs['video_vae_name'] == 'video.safetensors' and kwargs['audio_vae_name'] == 'audio.safetensors'
    ns = legacy_namespace(); loaded = []; called = {}
    image = types.SimpleNamespace(shape=(1, 640, 960, 3))
    video = types.SimpleNamespace(shape=(124, 640, 960, 3))
    def load_image(name):
        if name: loaded.append(name); return image
    def load_video(name, length):
        assert length == 124
        if name: loaded.append(name); return video, None
        return None, None
    def load_audio(name):
        if name: loaded.append(name); return {'audio': name}
    loader_calls = []
    class CLIPLoader:
        def load_clip(self, name, kind): loader_calls.append((name, kind)); return ('CLIP',)
    class VAELoader:
        def load_vae(self, name): loader_calls.append(name); return (name,)
    def conditioning(*args):
        called['conditioning'] = args
        return ('POSITIVE', {'samples': 'AV'}, None, args[3], '{}', 'task=' + task)
    ns.update(_load_image_file=load_image, _load_audio_file=load_audio, _load_video_frames=load_video,
              _trim_audio_to_duration=lambda audio, seconds: audio, _apply_audio_selection=lambda audio, selection: audio,
              align_frame_count_down=lambda n: n - ((n-5) % 17),
              nodes=types.SimpleNamespace(CLIPLoader=CLIPLoader, VAELoader=VAELoader), build_conditioning=conditioning,
              _release_text_encoder=lambda clip: called.update(released=clip), build_source_manifest=lambda **kw: {'mock': True},
              folder_paths=types.SimpleNamespace(get_input_directory=lambda: 'mock-input'))
    bundle = ns['MiniMaxH3IntegrationGH'].execute(**kwargs)[0]
    assert set(loaded) == set(media.values())
    assert bundle['width'] == 960 and bundle['height'] == 544 and bundle['length'] == 124
    assert loader_calls == [('clip.safetensors', 'minimax'), 'video.safetensors', 'audio.safetensors']
    assert called['released'] == 'CLIP'
    args = called['conditioning']; assert args[3] == 'A paper boat sails.' and args[6] == 124
    assert (args[15] is not None) == ('first_frame' in media)
    assert (args[16] is not None) == ('last_frame' in media)
    assert set(args[17]) == ({'ref_image_3'} if task == 'ref2va' else set())
    assert set(args[18]) == ({'ref_video_2'} if task == 'ref2va' else set())
    assert set(args[20]) == ({'ref_audio_1'} if task == 'ref2va' else set())
    expanded = ns['MiniMaxH3IntegrationAdapterGH'].execute(bundle)
    assert expanded.args[:4] == ('POSITIVE', {'samples': 'AV'}, 'video.safetensors', 'audio.safetensors')
    assert expanded[4] == (1 if task == 'ref2va' else 0)  # existing Model Switch selector
    ns['setup_dual_clock_sampling_gh'] = lambda model, latent, *args: (model, 'SAMPLER', 'SIGMAS')
    downstream = ns['MiniMaxH3DualClockT8GH'].execute('MODEL_AFTER_LORA_SWITCH', expanded[1], 4, 12, 3)
    assert downstream.args == ('MODEL_AFTER_LORA_SWITCH', 'SAMPLER', 'SIGMAS')
    ns['decode_av_latent'] = lambda latent, vv, av: ('FRAMES', 'AUDIO', 'VIDEO_LATENT', 'AUDIO_LATENT')
    ns['_schedule_background_model_cleanup'] = lambda: None
    assert ns['MiniMaxH3AVDecodeT8GH'].execute(expanded[1], expanded[2], expanded[3]).args[:2] == ('FRAMES', 'AUDIO')


def test_model_cache_boundary_and_model_change(local_module):
    a = local_module.GHLocalVideoInputGH.execute(**config()).expand
    b = local_module.GHLocalVideoInputGH.execute(**config(prompt='Changed')).expand
    c = local_module.GHLocalVideoInputGH.execute(**config(model_name='h3-ref.safetensors')).expand
    assert a['0'] == b['0'] and a['1'] != b['1']
    assert a['0'] != c['0'] and a['1'] == c['1']
    assert local_module.GHLocalVideoInputGH.execute(**config()).expand == a


@pytest.mark.parametrize('aspect', ['adaptive', '21:9', '16:9', '4:3', '1:1', '3:4', '9:16'])
@pytest.mark.parametrize('mp', [0.2, 0.5, 2.0])
def test_exact_old_canvas_and_duration_grid(aspect, mp):
    ns = legacy_namespace(); w, h = ns['calculate_canvas'](aspect, mp, 800, 600)
    assert w % 32 == h % 32 == 0
    if aspect == '1:1': assert w == h
    for duration in (2, 5, 10, 30):
        count = ns['calculate_length'](duration)
        assert count % 17 == 5 and count >= duration * 24 and count - duration * 24 < 17


@pytest.mark.parametrize('changes', [{'main_mode': 'bad'}, {'main_mode': 'all_reference'}, {'hybrid_audio': 'only.wav'},
    {'duration_seconds': 31}, {'duration_seconds': 1}, {'duration_seconds': 2.5}, {'megapixels': 0.1}, {'megapixels': 3},
    {'aspect': '2:1'}, {'model_name': 'missing'}, {'clip_name': 'missing'}, {'video_vae_name': 'missing'}, {'audio_vae_name': 'missing'},
    {'first_frame': '../bad.png'}, {'last_frame': 'C:/bad.png'}, {'ref_image_10': 'bad.png'}])
def test_invalid_inputs_fail_before_graph_or_sampling(local_module, changes):
    with pytest.raises(ValueError): local_module.GHLocalVideoInputGH.execute(**config(**changes))


def test_inactive_media_never_loaded_and_state_roundtrip():
    raw = {'schema_version': 1, 'mode': 'text_keyframes', 'prompt': '<Picture 1>',
           'media': [['first_frame', {'name': 'a.png', 'kind': 'image'}], ['ref_video_2', {'name': 'missing.mp4', 'kind': 'video'}]]}
    saved = local_state(json.dumps(raw)); active, task = execution_state(saved)
    assert task == 'i2va' and [s for s, _ in active['media']] == ['first_frame']
    assert local_state(json.dumps(saved)) == raw


@pytest.mark.parametrize('bad', [{'secret': 'x'}, {'mode': []}, {'media': {}}, {'schema_version': True},
    {'media': [['ref_image_1', {'name': 'a.png', 'runtime': {}}]]},
    {'media': [['ref_audio_1', {'name': 'a.wav', 'trimStart': 2, 'trimEnd': 1}]]}])
def test_strict_local_state_rejects_runtime_and_invalid_fields(bad):
    with pytest.raises(ValueError): local_state(bad)


def test_local_tags_not_cloud_mapping():
    assert prepare_prompt('<Picture 1> to <Picture 2>', {'pictures': 2}, task_type='fl2va')[0] == 'picture 1 to picture 2'
    assert prepare_prompt('<Picture 1>', {'pictures': 1}, task_type='l2va')[0] == '<Picture 1>'
    assert pack_media_tag_ordinals('<Picture 3> <Video 2>', {'picture': {3: 1}, 'video': {2: 1}}) == '<Picture 1> <Video 1>'
    with pytest.raises(ValueError): prepare_prompt('<Picture 2>', {'pictures': 1}, task_type='i2va')


def test_legacy_classes_unchanged_except_registration():
    # Fixed fingerprints of the four production classes at the v0.2.7.1 baseline.
    import hashlib
    expected = json.loads((ROOT / 'tests/fixtures/local_legacy_class_hashes.json').read_text())
    tree = ast.parse((ROOT / 'nodes.py').read_text(encoding='utf-8'))
    for item in tree.body:
        if isinstance(item, ast.ClassDef) and item.name in expected:
            assert hashlib.sha256(ast.dump(item).encode()).hexdigest() == expected[item.name]


def test_schema_seven_settings_output_order_unique_registration(local_module, monkeypatch):
    def socket(kind):
        return types.SimpleNamespace(Input=lambda id, **kw: {'id': id, 'type': kind, **kw},
                                     Output=lambda id=None, **kw: {'id': id, 'type': kind, **kw})
    for kind in ('Combo', 'Float', 'Int', 'String', 'Model', 'Audio'):
        setattr(local_module.io, kind, socket(kind))
    local_module.io.Custom = socket
    local_module.io.Schema = lambda **kw: types.SimpleNamespace(**kw)
    legacy = types.ModuleType('hutx_minimax_h3_testpkg.nodes')
    legacy.DEFAULT_CLIP = 'clip.safetensors'; legacy.DEFAULT_VIDEO_VAE = 'video.safetensors'; legacy.DEFAULT_AUDIO_VAE = 'audio.safetensors'
    legacy._default_model = lambda options, preferred: preferred if preferred in options else options[0]
    monkeypatch.setitem(sys.modules, legacy.__name__, legacy)
    schema = local_module.GHLocalVideoInputGH.define_schema()
    assert schema.node_id == 'GHLocalVideoInputGH' and schema.enable_expand
    assert schema.category == 'HuTX/MiniMax H3 Studio/Local'
    assert [i['id'] for i in schema.inputs[:7]] == ['model_name','clip_name','video_vae_name','audio_vae_name','aspect','megapixels','duration_seconds']
    assert [o['type'] for o in schema.outputs] == ['Model','MiniMax','String']
    assert schema.inputs[0]['options'] == ['h3.safetensors', 'h3-ref.safetensors']
    assert schema.inputs[5]['min'] == 0.2 and schema.inputs[5]['max'] == 2.0 and schema.inputs[5]['step'] == 0.1
    tree = ast.parse((ROOT / 'nodes.py').read_text(encoding='utf-8'))
    extension = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MiniMaxH3IntegrationExtension')
    returned = next(n for n in ast.walk(extension) if isinstance(n, ast.Return))
    ids = [n.id for n in returned.value.elts]
    assert len(ids) == len(set(ids)) == 15
    assert 'GHMultiSpeechInputGH' in ids
    assert ids == ['GHLocalVideoInputGH', 'GHLocalVideoInputOutputGH',
                   'GHLocalVideoInputDualEngineGH', 'GHLocalVideoDualEngineOutputGH', 'MiniMaxH3IntegrationGH',
                   'MiniMaxH3IntegrationAdapterGH', 'MiniMaxH3DualClockT8GH', 'MiniMaxH3AVDecodeT8GH',
                   'GHCloudVideoInputGH', 'FalH3MaxVideoGH', 'GHSpeechInputGH', 'GHMultiSpeechInputGH',
                   'H3HyperFlowCompatibilityGH', 'H3HyperFlowPatchGH', 'H3HyperFlowSamplerGH']


def test_output_model_guard_and_actual_canvas_report(local_module, monkeypatch):
    model_base = types.ModuleType('comfy.model_base')
    model_base.MiniMaxH3 = type('MiniMaxH3', (), {})
    monkeypatch.setitem(sys.modules, 'comfy.model_base', model_base)
    bundle = {'width': 960, 'height': 544, 'length': 124, 'report': 'task=fl2va'}
    with pytest.raises(ValueError, match='not a MiniMax H3'):
        local_module.GHLocalVideoInputOutputGH.execute(object(), bundle, '{}')
    model = types.SimpleNamespace(model=model_base.MiniMaxH3())
    result = local_module.GHLocalVideoInputOutputGH.execute(model, bundle, '{"task":"fl2va"}')
    assert result[0] is model and result[1] is bundle
    report = json.loads(result[2]); assert report['actual_seconds'] == 124/24
    assert (report['width'], report['height'], report['fps']) == (960, 544, 24)


@pytest.mark.parametrize('model,extra', [
    ('minimax_h3_fl2va_pruned_int8_convrot.safetensors', {'main_mode': 'all_reference', 'ref_image_1': 'a.png'}),
    ('minimax_h3_ref2va_pruned_int8_convrot.safetensors', {}),
])
def test_known_checkpoint_task_mismatch_fails_before_loading(local_module, monkeypatch, model, extra):
    original = local_module.folder_paths.get_filename_list
    monkeypatch.setattr(local_module.folder_paths, 'get_filename_list', lambda folder: [model] if folder == 'diffusion_models' else original(folder))
    with pytest.raises(ValueError, match='checkpoint'):
        local_module.GHLocalVideoInputGH.execute(**config(model_name=model, **extra))
