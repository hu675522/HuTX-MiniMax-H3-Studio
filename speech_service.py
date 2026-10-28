"""Bounded process-memory audio cache shared by preview and node execution."""
import io
import json
import secrets
import threading
import time
import wave
from collections import OrderedDict
from dataclasses import dataclass

from .speech_capabilities import video_capabilities
from .speech_providers import MockSpeechProvider
from .speech_validation import PCM, SpeechError, SpeechCancelled, fingerprint, validate_request
from .speech_errors import SpeechFailure


def catalog():
    from .speech_local import local_status,local_voices
    from .speech_credentials import SPEECH_CREDENTIALS
    from .speech_providers.bailian import VOICES
    from .speech_oss import configured
    local=local_status();cloud=SPEECH_CREDENTIALS.status()
    return {'stage':5,'real_synthesis_available':local['available'] or cloud['configured'],
        'notice':'本地 CosyVoice / 百炼北京。云端克隆使用自有 OSS 临时上传，需额外配置；云端生成可能计费。',
        'engines':[{'id':'local',**local,'voices':local_voices()},
                   {'id':'cloud','available':cloud['configured'],'voices':VOICES,'clone_upload_configured':configured()}],
        'credential':cloud,'video_targets':video_capabilities()}


def decode_wav(data):
    try:
        with wave.open(io.BytesIO(data),'rb') as f:
            if f.getsampwidth()!=2:raise ValueError()
            return PCM(f.readframes(f.getnframes()),f.getframerate(),f.getnchannels()).validate()
    except Exception:raise SpeechError('无法解码 PCM16 WAV 音频。') from None


def wav_bytes(pcm):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as f:
        f.setnchannels(pcm.channels)
        f.setsampwidth(2)
        f.setframerate(pcm.sample_rate)
        f.writeframes(pcm.data)
    return stream.getvalue()


def read_reference(filename):
    if not filename:
        return None
    import folder_paths
    from pathlib import Path
    root = Path(folder_paths.get_input_directory()).resolve()
    if not isinstance(filename, str):
        raise SpeechError('参考音频路径无效。')
    path = (root / filename).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > 48_000_000:
        raise SpeechError('请选择 input 目录内有效的参考音频。')
    try:
        with wave.open(str(path), 'rb') as f:
            if f.getsampwidth() != 2 or f.getnframes() > f.getframerate() * 120:
                raise SpeechError('只接受最多 120 秒的 PCM16 WAV 参考音频。')
            return PCM(f.readframes(f.getnframes()), f.getframerate(), f.getnchannels()).validate()
    except SpeechError:
        raise
    except Exception:
        raise SpeechError('请使用有效的 PCM16 WAV 参考音频。') from None


@dataclass(frozen=True)
class Result:
    audio_id: str
    pcm: PCM
    elapsed: float
    engine: str
    mode: str
    is_mock: bool = True
    model_version: str = 'hutx-mock-pcm-v1'
    input_fingerprint: str = ''

    def public(self, cached=False):
        return {'audio_id': self.audio_id, 'duration_seconds': self.pcm.seconds,
                'report': {'status': 'mock' if self.is_mock else 'success', 'is_mock': self.is_mock, 'engine': self.engine, 'mode': self.mode,
                           'model_version': self.model_version, 'duration_seconds': self.pcm.seconds,
                           'elapsed_seconds': self.elapsed, 'cache_hit': cached,
                           'notice': '测试音，不是克隆语音；未调用模型或云端 API。' if self.is_mock else '口播音频已生成；请试听确认台词完整性。'}}


class SpeechService:
    def __init__(self, provider=None, capacity=8, ttl=1800,real_providers=None):
        self.provider = provider or MockSpeechProvider()
        self.capacity, self.ttl = capacity, ttl
        self.cache = OrderedDict()
        self.inflight = set()
        self.lock = threading.RLock()
        self.real_providers=real_providers

    def _prune(self):
        now = time.monotonic()
        for key, (created, _) in list(self.cache.items()):
            if now - created > self.ttl:
                del self.cache[key]

    def generate(self, raw, reference=None, cancel=None):
        request = validate_request(raw, reference)
        input_fingerprint=fingerprint(request,reference)
        provider=self.provider;scope=''
        if not request['mock_demo']:
            with self.lock:
                if self.real_providers is None:
                    from .speech_local import LocalSpeechProvider
                    from .speech_providers.bailian import BailianSpeechProvider
                    self.real_providers={'local':LocalSpeechProvider(),'cloud':BailianSpeechProvider()}
            provider=self.real_providers[request['engine']]
            if request['engine']=='local' and request['mode']=='preset':
                from .speech_local import preset_reference
                reference,transcript=preset_reference(request['voice'])
                request=dict(request,mode='clone',reference_text=transcript)
            if hasattr(provider,'scope'):scope=provider.scope()
        cancel = cancel or threading.Event()
        if cancel.is_set():
            raise SpeechCancelled('已取消。')
        version=getattr(provider,'version','hutx-mock-pcm-v1')
        key = fingerprint(request, reference,version,scope)
        with self.lock:
            self._prune()
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key][1], True
            if key in self.inflight:
                raise SpeechError('相同口播正在生成，请勿重复提交。')
            self.inflight.add(key)
        started = time.perf_counter()
        try:
            pcm = provider.synthesize(request, reference, cancel).validate()
            if cancel.is_set():
                raise SpeechCancelled('已取消。')
            result = Result(secrets.token_hex(16), pcm, time.perf_counter() - started, request['engine'], raw.get('mode','clone'),request['mock_demo'],version,input_fingerprint)
            with self.lock:
                self.cache[key] = (time.monotonic(), result)
                while len(self.cache) > self.capacity:
                    self.cache.popitem(last=False)
            return result, False
        except SpeechCancelled:
            raise
        except SpeechFailure:
            raise
        except Exception:
            raise SpeechError('口播生成失败，请检查执行端配置。') from None
        finally:
            with self.lock:
                self.inflight.discard(key)

    def audio(self, audio_id):
        with self.lock:
            self._prune()
            for _, result in self.cache.values():
                if result.audio_id == audio_id:
                    return wav_bytes(result.pcm)
        raise SpeechError('试听音频已失效，请重新生成。')

    def adopt(self,audio_id):
        from .speech_snapshot import save_snapshot
        with self.lock:
            self._prune()
            for _,result in self.cache.values():
                if result.audio_id==audio_id:return save_snapshot(result)
        raise SpeechError('试听音频已失效，请重新生成。')


SPEECH_SERVICE = SpeechService()
