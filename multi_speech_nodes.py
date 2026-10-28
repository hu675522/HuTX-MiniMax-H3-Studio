"""Three independent, explicitly adopted speech snapshots. Never generates at Queue."""
import json
import hashlib
from comfy_api.latest import io
from .plugin_meta import NODE_CATEGORY
from .speech_validation import FIELDS, SpeechError, validate_request, fingerprint
from .speech_service import read_reference
from .speech_snapshot import load_snapshot

ROLE_FIELDS = FIELDS | {'reference_file', 'adopted_audio_file', 'name', 'enabled', 'collapsed', 'reference_name'}


def read_role(raw):
    try:
        role = json.loads(raw or '{}')
        if not isinstance(role, dict) or set(role) - ROLE_FIELDS:
            raise ValueError()
        if type(role.get('enabled', True)) is not bool:
            raise ValueError()
    except (ValueError, TypeError):
        raise SpeechError('角色配置无效，请重新配置角色。') from None
    return role


def adopted_role(raw, letter):
    role = read_role(raw)
    # Blank / unused cards produce no AUDIO, never silence or an implicit TTS call.
    if not role.get('enabled', True) or not str(role.get('text', '')).strip():
        return None
    if not role.get('adopted_audio_file'):
        raise SpeechError(f'角色 {letter} 请先生成、试听并采用音频。')
    reference = read_reference(role.get('reference_file', '')) if role.get('mode', 'clone') == 'clone' else None
    request = validate_request({k: v for k, v in role.items() if k in FIELDS}, reference)
    return load_snapshot(role['adopted_audio_file'], fingerprint(request, reference))


class GHMultiSpeechInputGH(io.ComfyNode):
    @classmethod
    def fingerprint_inputs(cls, role_A='{}', role_B='{}', role_C='{}'):
        # Revalidate both source reference and adopted snapshot even on graph cache hits.
        return tuple(hashlib.sha256(result.pcm.data).hexdigest() if result else 'unused'
            for result in (adopted_role(raw, letter) for letter, raw in zip('ABC', (role_A, role_B, role_C))))

    @classmethod
    def define_schema(cls):
        return io.Schema(node_id='GHMultiSpeechInputGH', display_name='HuTX · 多角色口播',
            category=NODE_CATEGORY + '/Speech',
            description='A/B/C 独立生成并采用，连接 Local reference_audio_1/2/3。空台词或停用角色输出空值；Queue 只校验并复用已采用快照。',
            inputs=[io.String.Input('role_' + letter, default='{}', multiline=True) for letter in 'ABC'],
            outputs=[*[io.Audio.Output('audio_' + letter) for letter in 'ABC'], io.String.Output('speech_report')])

    @classmethod
    def execute(cls, role_A='{}', role_B='{}', role_C='{}'):
        import torch
        results = [adopted_role(raw, letter) for letter, raw in zip('ABC', (role_A, role_B, role_C))]
        audios, report = [], []
        for letter, result in zip('ABC', results):
            if result is None:
                audios.append(None)
                report.append({'role': letter, 'configured': False})
                continue
            pcm = result.pcm
            waveform = torch.frombuffer(bytearray(pcm.data), dtype=torch.int16).float().reshape(-1, pcm.channels).T.unsqueeze(0) / 32767
            audios.append({'waveform': waveform, 'sample_rate': pcm.sample_rate})
            report.append({'role': letter, 'configured': True, 'duration_seconds': pcm.seconds})
        return io.NodeOutput(*audios, json.dumps(report, ensure_ascii=False))
