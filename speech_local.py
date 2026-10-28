"""CosyVoice isolated process runner and local user-owned preset bank."""
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .speech_validation import SpeechError, SpeechCancelled
from .speech_errors import SpeechFailure

ROOT = Path(__file__).resolve().parent
LOCAL_LOCK = threading.Lock()


def release_comfy_models():
    try:
        import comfy.model_management as management
        management.unload_all_models();management.soft_empty_cache()
    except ImportError:pass


def runtime_paths():
    runtime = Path(os.environ.get('HUTX_SPEECH_RUNTIME', str(ROOT / '.speech-runtime')))
    return runtime, runtime / 'env/Scripts/python.exe', runtime / 'CosyVoice', runtime / 'models/Fun-CosyVoice3-0.5B-2512'


def local_status():
    runtime, python, code, model = runtime_paths()
    required = [python, runtime/'environment-ready.json',code/'cosyvoice/cli/cosyvoice.py', model/'hutx-model-lock.json',
                model/'llm.pt', model/'flow.pt', model/'hift.pt', model/'speech_tokenizer_v3.onnx']
    required += [model.parent/'wetext'/language/'tn'/name
                 for language in ('en','zh') for name in ('tagger.fst','verbalizer.fst')]
    required += [model.parent/'quality/silero_vad.onnx']
    ready = all(p.is_file() for p in required)
    return {'available': ready, 'notice': '本地运行文件已就绪。' if ready else '尚未安装完整独立 CosyVoice 环境。'}


def voice_root():
    import folder_paths
    return Path(folder_paths.get_user_directory()) / 'default/HuTX-MiniMax-H3-Studio/speech_voices'


def local_voices():
    result = builtin_voices()
    try:
        for path in voice_root().glob('*.json'):
            data = json.loads(path.read_text(encoding='utf-8'))
            if path.with_suffix('.wav').is_file():
                result.append({'id': 'local:' + path.stem, 'name': str(data['name'])[:80]})
        return result
    except (ImportError, AttributeError, OSError, ValueError, KeyError):
        return result


def builtin_voices():
    labels = {'a': '温柔女声', 'b': '沉稳男声'}
    return [{'id':'local:official-'+name,'name':labels[name]}
            for name in ('a','b') if (ROOT/'assets/speech_voices'/f'{name}.wav').is_file()]


def save_voice(name, reference_text, reference):
    from .speech_service import wav_bytes
    if not isinstance(name, str) or not name.strip() or len(name) > 80 or not isinstance(reference_text, str) or not reference_text.strip() or len(reference_text) > 4000:
        raise SpeechError('请填写音色名称和准确的参考录音原文。')
    reference.validate()
    identity = hashlib.sha256(wav_bytes(reference) + reference_text.encode()).hexdigest()[:24]
    root = voice_root();root.mkdir(parents=True, exist_ok=True)
    (root/(identity+'.wav')).write_bytes(wav_bytes(reference))
    (root/(identity+'.json')).write_text(json.dumps({'name':name,'reference_text':reference_text},ensure_ascii=False),encoding='utf-8')
    return {'id':'local:'+identity,'name':name}


def preset_reference(voice):
    import re
    from .speech_service import decode_wav
    if voice in ('local:official-a','local:official-b'):
        name=voice[-1]
        try:
            return decode_wav((ROOT/'assets/speech_voices'/f'{name}.wav').read_bytes()), ('希望你以后能够做的比我还好呦。' if name=='a' else '')
        except Exception:raise SpeechError('内置示例声线文件不可用，请重新安装完整插件。') from None
    if not re.fullmatch(r'local:[a-f0-9]{24}', voice):raise SpeechError('请选择已保存的本机音色。')
    base=voice_root()/voice.split(':')[1]
    try:
        info=json.loads(base.with_suffix('.json').read_text(encoding='utf-8'))
        return decode_wav(base.with_suffix('.wav').read_bytes()), info['reference_text']
    except Exception:raise SpeechError('本机音色已失效，请重新保存。') from None


class LocalSpeechProvider:
    version = 'cosyvoice3-29e01c4e-074ca6dc-asr1'

    def synthesize(self, request, reference, cancel):
        from .speech_service import wav_bytes, decode_wav
        if not local_status()['available']:raise SpeechError('尚未安装完整独立 CosyVoice 环境。')
        from .speech_quality import check_reference_energy
        check_reference_energy(reference)
        if not LOCAL_LOCK.acquire(blocking=False):raise SpeechError('本地 TTS 正在运行，请稍后重试。')
        process=None
        try:
            if cancel.is_set():raise SpeechCancelled()
            runtime, python, code, model=runtime_paths()
            # Queue execution is serial; preview route refuses an occupied H3 queue.
            release_comfy_models()
            with tempfile.TemporaryDirectory(prefix='hutx-speech-') as directory:
                temp=Path(directory);(temp/'reference.wav').write_bytes(wav_bytes(reference))
                payload={'text':request['text'],'reference_text':request['reference_text'],'speed':request['speed']}
                (temp/'request.json').write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
                env={k:v for k,v in os.environ.items() if not any(word in k.upper() for word in ('API_KEY','FAL_KEY','TOKEN','SECRET'))}
                env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONIOENCODING='utf-8',PYTHONUTF8='1')
                process=subprocess.Popen([str(python),str(ROOT/'speech_worker.py'),str(code),str(model),str(temp)],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                try:
                    deadline=time.monotonic()+600
                    while process.poll() is None:
                        if cancel.wait(.1):raise SpeechCancelled()
                        if time.monotonic()>deadline:raise SpeechFailure('local_timeout')
                    if (temp/'error.json').exists():
                        try:code=json.loads((temp/'error.json').read_text(encoding='utf-8')).get('code')
                        except Exception:code='local_failure'
                        raise SpeechFailure(code if code in ('reference_speech','reference_transcript') else 'local_failure')
                    if process.returncode or not (temp/'output.wav').exists():raise SpeechFailure('local_failure')
                    return decode_wav((temp/'output.wav').read_bytes())
                finally:
                    # Stop the worker before TemporaryDirectory removes files on Windows.
                    if process.poll() is None:process.kill();process.wait(timeout=10)
        finally:
            if process is not None and process.poll() is None:
                process.kill();process.wait(timeout=10)
            LOCAL_LOCK.release()
