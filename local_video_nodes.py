"""Independent Local input, expanding into the proven Local execution graph."""
from __future__ import annotations

import json
import math

import folder_paths
from comfy_api.latest import io
from comfy_execution.graph_utils import GraphBuilder

from .local_video_state import ASPECTS, MEDIA_SLOTS, execution_state, local_state
from .plugin_meta import NODE_CATEGORY


class GHLocalVideoInputGH(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        from .nodes import DEFAULT_CLIP, DEFAULT_VIDEO_VAE, DEFAULT_AUDIO_VAE, _default_model
        def model_input(name, folder, preferred=''):
            names = folder_paths.get_filename_list(folder)
            return io.Combo.Input(name, options=names, default=_default_model(names, preferred))
        return io.Schema(
            node_id='GHLocalVideoInputGH', display_name='HuTX · 本地视频输入 · 5合1',
            category=NODE_CATEGORY + '/Local', enable_expand=True,
            description='Local H3 input. MODEL remains connectable through LoRA / Model Switch / DualClock / Sampler. No cloud calls.',
            inputs=[
                model_input('model_name', 'diffusion_models', 'minimax_h3_fl2va_pruned_w4a8_mixed.safetensors'),
                model_input('clip_name', 'text_encoders', DEFAULT_CLIP),
                model_input('video_vae_name', 'vae', DEFAULT_VIDEO_VAE),
                model_input('audio_vae_name', 'vae', DEFAULT_AUDIO_VAE),
                io.Combo.Input('aspect', options=list(ASPECTS), default='adaptive'),
                io.Float.Input('megapixels', default=0.5, min=0.2, max=2.0, step=0.1, round=0.1),
                io.Int.Input('duration_seconds', default=5, min=2, max=30, step=1),
                io.Combo.Input('main_mode', options=['text_keyframes', 'all_reference'], default='text_keyframes'),
                io.String.Input('prompt', default='', multiline=True),
                *[io.String.Input(slot, default='', optional=True, extra_dict={'hidden': True}) for slot in MEDIA_SLOTS],
                io.String.Input('gh_local_state_json', default='', optional=True, extra_dict={'hidden': True}),
                io.Audio.Input('driver_audio', optional=True),
                *[io.Audio.Input(f'reference_audio_{i}', optional=True) for i in (1, 2, 3)],
                io.Combo.Input('driver_model_family',options=['unconfirmed','FL2VA','Ref2VA'],default='unconfirmed',optional=True),
                io.Combo.Input('driver_conflict',options=['reject_conflicts','use_connected_audio'],default='reject_conflicts',optional=True),
                io.Combo.Input('driver_slot',options=['auto','hybrid_audio','ref_audio_1','ref_audio_2','ref_audio_3'],default='auto',optional=True),
            ],
            outputs=[io.Model.Output('model'), io.Custom('MiniMax').Output('integration'), io.String.Output('local_report')],
        )

    @classmethod
    def execute(cls, model_name, clip_name, video_vae_name, audio_vae_name, aspect='adaptive', megapixels=0.5,
                duration_seconds=5, main_mode='text_keyframes', prompt='', gh_local_state_json='',
                driver_audio=None,driver_model_family='unconfirmed',driver_conflict='reject_conflicts',driver_slot='auto',
                reference_audio_1=None,reference_audio_2=None,reference_audio_3=None,**media):
        if aspect not in ASPECTS or not math.isfinite(float(megapixels)) or not 0.2 <= float(megapixels) <= 2.0:
            raise ValueError('Local aspect / megapixels must use the supported 0.2–2.0 MP range.')
        if type(duration_seconds) is not int or not 2 <= duration_seconds <= 30:
            raise ValueError('Local duration must be an integer from 2 to 30 seconds.')
        selected = {'model_name': model_name, 'clip_name': clip_name, 'video_vae_name': video_vae_name, 'audio_vae_name': audio_vae_name}
        for key, folder in [('model_name', 'diffusion_models'), ('clip_name', 'text_encoders'), ('video_vae_name', 'vae'), ('audio_vae_name', 'vae')]:
            if selected[key] not in folder_paths.get_filename_list(folder):
                raise ValueError(f'Local {key} is not available in the configured ComfyUI model directories.')
        if set(media) - set(MEDIA_SLOTS):
            raise ValueError('Unknown Local input fields.')
        state, task = execution_state(local_state(gh_local_state_json, mode=main_mode, prompt=prompt, media=media))
        # These installed official checkpoint families have separate trained tasks.
        # Do not infer capabilities for third-party H3 checkpoint names.
        basename = model_name.replace('\\', '/').rsplit('/', 1)[-1].lower()
        if basename.startswith('minimax_h3_fl2va_') and task == 'ref2va':
            raise ValueError('Ref2VA requires the Ref2VA checkpoint; select a reference model / 请切换全能参考主模型。')
        if basename.startswith('minimax_h3_ref2va_') and task != 'ref2va':
            raise ValueError('Text/keyframe modes require the FL2VA checkpoint / 请切换文本或首尾帧主模型。')
        driver_report=None;drive_ordinal=1;user_duration=duration_seconds
        reference_report = None
        role_audio = (reference_audio_1, reference_audio_2, reference_audio_3)
        # Keeping all four cables attached is supported. The selected task owns
        # the active family: Ref2VA consumes A/B/C; keyframes consume driver_audio.
        if task == 'ref2va' and any(a is not None for a in role_audio):
            from .multi_speech_bridge import bridge_references
            from .nodes import calculate_length
            state, reference_report = bridge_references(state, task,
                role_audio, duration_seconds, calculate_length)
        if driver_audio is not None and reference_report is None:
            from .speech_bridge import bridge_audio
            from .nodes import calculate_length
            state,duration_seconds,drive_ordinal,driver_report=bridge_audio(
                state,task,driver_audio,duration_seconds,driver_model_family,driver_conflict,driver_slot,calculate_length)
        # Use the host's graph/node cache, not a second process-global model cache.
        # A prompt/media change does not change the UNETLoader inputs.
        graph = GraphBuilder()
        model = graph.node('UNETLoader', unet_name=model_name, weight_dtype='default')
        kwargs = {slot: '' for slot in MEDIA_SLOTS}
        kwargs.update({slot: entry['name'] for slot, entry in state['media']})
        conditioning = graph.node('MiniMaxH3IntegrationGH',
            main_mode=state['mode'], prompt=state['prompt'], aspect=aspect, megapixels=megapixels,
            duration_seconds=duration_seconds, clip_name=clip_name, video_vae_name=video_vae_name, audio_vae_name=audio_vae_name,
            task_type='auto', audio_mode='reference_only' if reference_report else 'lock_source', audio_denoise_strength=0.0, drive_audio_ordinal=drive_ordinal,
            strict_prompt_tags=True, ref_image_size='match', gh_state_json=json.dumps(state, ensure_ascii=False), **kwargs)
        configuration = {**selected, 'task': task, 'aspect': aspect, 'megapixels': megapixels, 'requested_seconds': duration_seconds}
        if driver_report is not None:configuration.update(driver_audio=driver_report,requested_seconds=user_duration)
        if reference_report is not None:configuration['reference_audio'] = reference_report
        output = graph.node('GHLocalVideoInputOutputGH', model=model.out(0), integration=conditioning.out(0), configuration=json.dumps(configuration))
        return io.NodeOutput(output.out(0), output.out(1), output.out(2), expand=graph.finalize())


class GHLocalVideoInputOutputGH(io.ComfyNode):
    """Expansion terminal: retain the old bundle and report actual computed values."""
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id='GHLocalVideoInputOutputGH', display_name='HuTX · Local Core Output',
            category=NODE_CATEGORY + '/Utilities',
            inputs=[io.Model.Input('model'), io.Custom('MiniMax').Input('integration'), io.String.Input('configuration')],
            outputs=[io.Model.Output('model'), io.Custom('MiniMax').Output('integration'), io.String.Output('local_report')])

    @classmethod
    def execute(cls, model, integration, configuration):
        from comfy.model_base import MiniMaxH3
        if not isinstance(getattr(model, 'model', None), MiniMaxH3):
            raise ValueError('The selected MODEL is not a MiniMax H3 model; sampling was not started.')
        config = json.loads(configuration)
        if config.get('driver_audio'):
            from .speech_bridge import verify_locked_bundle
            verify_locked_bundle(integration,config['driver_audio'])
            config['driver_audio']['lock_source_verified']=True
        report = {**config, 'width': integration['width'], 'height': integration['height'],
                  'frame_count': integration['length'], 'actual_seconds': integration['length'] / 24.0,
                  'fps': 24, 'conditioning_report': integration['report']}
        report_text = json.dumps(report, ensure_ascii=False, indent=2)
        return io.NodeOutput(model, integration, report_text, ui={'local_report': [report_text]})
