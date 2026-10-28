"""Separate optional mock speech node; old video schemas remain unchanged."""
import hashlib
import json
from comfy_api.latest import io
from .plugin_meta import NODE_CATEGORY
from .speech_service import SPEECH_SERVICE, read_reference
from .speech_validation import PCM, SpeechError


def tensor_reference(audio):
    import torch
    waveform = audio.get('waveform')
    if not isinstance(waveform, torch.Tensor) or waveform.ndim != 3 or waveform.shape[0] != 1:
        raise SpeechError('参考 AUDIO 必须是单批次 [1, channels, samples]。')
    if waveform.shape[1] not in (1, 2) or not torch.isfinite(waveform).all():
        raise SpeechError('参考 AUDIO 声道或采样值无效。')
    data = (waveform.detach().cpu().clamp(-1, 1)[0].T * 32767).round().to(torch.int16).contiguous().numpy().tobytes()
    return PCM(data, audio.get('sample_rate'), int(waveform.shape[1])).validate()


class GHSpeechInputGH(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id='GHSpeechInputGH', display_name='HuTX · 口播音频生成',
            category=NODE_CATEGORY + '/Speech',
            description='本地 CosyVoice / 百炼北京。关闭 Mock 后执行真实语音生成；云端可能计费。',
            inputs=[io.Combo.Input('engine', options=['local', 'cloud'], default='local'),
                    io.Combo.Input('mode', options=['clone', 'preset'], default='clone'),
                    io.String.Input('text', multiline=True, default='你好，这是口播测试。'),
                    io.String.Input('reference_text', multiline=True, default=''),
                    io.String.Input('reference_file', default=''),
                    io.String.Input('voice', default='local:demo-a'),
                    io.Float.Input('speed', default=1.0, min=0.5, max=2.0, step=0.1),
                    io.Boolean.Input('mock_demo', default=False),
                    io.Int.Input('revision', default=0, min=0, max=2**31-1),
                    io.Combo.Input('cloud_model',options=['auto','cosyvoice-v3.5-plus','cosyvoice-v3.5-flash','cosyvoice-v3-flash','qwen-audio-3.1-tts-flash'],default='auto'),
                    io.String.Input('workspace',default=''),
                    io.String.Input('adopted_audio_file',default='',optional=True,extra_dict={'hidden':True}),
                    io.Audio.Input('reference_audio', optional=True)],
            outputs=[io.Audio.Output('audio'), io.Float.Output('duration_seconds'), io.String.Output('speech_report')])

    @classmethod
    def fingerprint_inputs(cls, reference_file='', reference_audio=None, adopted_audio_file='', **kwargs):
        if adopted_audio_file:
            from .speech_validation import FIELDS,validate_request,fingerprint
            from .speech_snapshot import load_snapshot
            reference=(tensor_reference(reference_audio) if reference_audio is not None else read_reference(reference_file)) if kwargs.get('mode')=='clone' else None
            parameters={k:v for k,v in kwargs.items() if k in FIELDS}
            result=load_snapshot(adopted_audio_file,fingerprint(validate_request(parameters,reference),reference))
            return hashlib.sha256(result.pcm.data).hexdigest()
        if kwargs.get('mode') == 'clone' and reference_audio is not None:
            reference = tensor_reference(reference_audio)
            return hashlib.sha256(reference.data + str((reference.sample_rate, reference.channels)).encode()).hexdigest()
        if kwargs.get('mode') != 'clone' or not reference_file:
            return 'speech-v1'
        reference = read_reference(reference_file)
        return hashlib.sha256(reference.data + str((reference.sample_rate, reference.channels)).encode()).hexdigest()

    @classmethod
    def execute(cls, engine='local', mode='clone', text='', reference_text='', reference_file='',
                voice='local:demo-a', speed=1.0, mock_demo=False, revision=0, reference_audio=None,cloud_model='auto',workspace='',adopted_audio_file=''):
        reference = None
        if mode == 'clone':
            reference = tensor_reference(reference_audio) if reference_audio is not None else read_reference(reference_file)
        parameters=dict(engine=engine, mode=mode, text=text,reference_text=reference_text, voice=voice,
                        speed=speed,mock_demo=mock_demo,revision=revision,cloud_model=cloud_model,workspace=workspace)
        if adopted_audio_file:
            from .speech_validation import validate_request,fingerprint
            from .speech_snapshot import load_snapshot
            result=load_snapshot(adopted_audio_file,fingerprint(validate_request(parameters,reference),reference));cached=True
        else:result,cached=SPEECH_SERVICE.generate(parameters,reference)
        import torch
        waveform = torch.frombuffer(bytearray(result.pcm.data), dtype=torch.int16).float().reshape(-1, result.pcm.channels).T.unsqueeze(0) / 32767
        public = result.public(cached)
        return io.NodeOutput({'waveform': waveform, 'sample_rate': result.pcm.sample_rate},
            result.pcm.seconds, json.dumps(public['report'], ensure_ascii=False), ui={'speech_result': [public]})
