"""Strict, secret-free speech request and PCM validation (no model imports)."""
import hashlib
import json
import math
from dataclasses import dataclass


class SpeechError(ValueError):
    pass


class SpeechCancelled(SpeechError):
    pass


@dataclass(frozen=True)
class PCM:
    data: bytes
    sample_rate: int
    channels: int = 1

    @property
    def seconds(self):
        return len(self.data) / (2 * self.channels * self.sample_rate)

    def validate(self):
        if type(self.sample_rate) is not int or not 8000 <= self.sample_rate <= 192000:
            raise SpeechError('音频采样率无效。')
        if type(self.channels) is not int or self.channels not in (1, 2) or not isinstance(self.data, bytes) or not self.data or len(self.data) % (2 * self.channels):
            raise SpeechError('音频必须是非空单声道或双声道 PCM16。')
        if self.seconds > 120:
            raise SpeechError('本阶段参考音频最多 120 秒。')
        return self


FIELDS = {'engine', 'mode', 'text', 'reference_text', 'voice', 'speed', 'mock_demo', 'revision','cloud_model','workspace'}


def validate_request(raw, reference=None):
    if not isinstance(raw, dict) or set(raw) - FIELDS:
        raise SpeechError('口播参数含不支持的字段；禁止传入凭证或运行时对象。')
    request = dict(engine='local', mode='clone', text='', reference_text='', voice='', speed=1.0,
                   mock_demo=False, revision=0,cloud_model='auto',workspace='')
    request.update(raw)
    if request['engine'] not in ('local', 'cloud') or request['mode'] not in ('clone', 'preset'):
        raise SpeechError('请选择有效的执行端与音色方式。')
    if type(request['mock_demo']) is not bool:
        raise SpeechError('Mock 开关无效。')
    if request['cloud_model'] not in ('auto','cosyvoice-v3.5-plus','cosyvoice-v3.5-flash','cosyvoice-v3-flash','qwen-audio-3.1-tts-flash'):
        raise SpeechError('语音模型无效。')
    from .speech_providers.bailian import endpoint
    endpoint(request['workspace'])
    for field in ('text', 'reference_text', 'voice'):
        if not isinstance(request[field], str) or len(request[field]) > 4000:
            raise SpeechError('文本字段类型无效或过长。')
    if not request['text'].strip():
        raise SpeechError('请填写新台词。')
    speed = request['speed']
    if type(speed) not in (int, float) or not math.isfinite(speed) or not 0.5 <= speed <= 2:
        raise SpeechError('语速必须在 0.5～2.0 之间。')
    # JSON preview may send 1; Comfy Float sends 1.0. They must share a cache key.
    request['speed'] = float(speed)
    if type(request['revision']) is not int or not 0 <= request['revision'] <= 2**31-1:
        raise SpeechError('重生成序号无效。')
    if request['mode'] == 'clone':
        if reference is None:
            raise SpeechError('请提供参考音频。')
        reference.validate()
        # The isolated local worker transcribes missing reference text offline.
        request['voice'] = ''
    else:
        if request['mock_demo'] and request['voice'] not in (request['engine'] + ':demo-a', request['engine'] + ':demo-b'):
            raise SpeechError('请选择当前执行端的 Mock 音色；音色不可跨端复用。')
        request['reference_text'] = ''
    return request


def fingerprint(request, reference, model_version='hutx-mock-pcm-v1',scope=''):
    info = {'parameters': request, 'model_version': model_version,'scope':scope}
    if request['mode'] == 'clone':
        info['reference'] = {'sha256': hashlib.sha256(reference.data).hexdigest(),
                             'sample_rate': reference.sample_rate, 'channels': reference.channels}
    return hashlib.sha256(json.dumps(info, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
