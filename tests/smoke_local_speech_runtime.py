"""Operator-only real local GPU check. No pytest collection and no cloud calls."""
import importlib
import json
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

root=Path(__file__).resolve().parents[1]
package=types.ModuleType('hutx_speech_smoke');package.__path__=[str(root)]
sys.modules[package.__name__]=package
local=importlib.import_module(package.__name__+'.speech_local')
service=importlib.import_module(package.__name__+'.speech_service')
validation=importlib.import_module(package.__name__+'.speech_validation')
# This operator runs outside ComfyUI, so there are no host models to unload.
local.release_comfy_models=lambda: None
runtime=root/'.speech-runtime'
out=root/'.test-artifacts/speech-stage34';out.mkdir(parents=True,exist_ok=True)
import soundfile as sf
samples,rate=sf.read(runtime/'CosyVoice/asset/zero_shot_prompt.wav')
sf.write(out/'official-reference-pcm16.wav',samples,rate,subtype='PCM_16')
reference=service.decode_wav((out/'official-reference-pcm16.wav').read_bytes())
request={'text':'很高兴见到你。今天我们一起测试本地声音克隆。',
         'reference_text':'希望你以后能够做的比我还好呦。','speed':1.0}
def memory():
    return subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.used','--format=csv,noheader'],text=True).strip()
before=memory();start=time.perf_counter()
pcm=local.LocalSpeechProvider().synthesize(request,reference,threading.Event())
(out/'local-cosyvoice.wav').write_bytes(service.wav_bytes(pcm))
elapsed=time.perf_counter()-start
after=memory()
cancel=threading.Event();timer=threading.Timer(5,cancel.set);timer.start()
try:
    local.LocalSpeechProvider().synthesize(request,reference,cancel)
    raise AssertionError('Cancellation did not stop the worker')
except validation.SpeechCancelled: pass
finally:timer.cancel()
assert local.LOCAL_LOCK.acquire(blocking=False);local.LOCAL_LOCK.release()
record={'status':'PASS','duration':pcm.seconds,'sample_rate':pcm.sample_rate,
        'elapsed_seconds':round(elapsed,3),'gpu_before':before,'gpu_after':after,
        'gpu_after_cancel':memory(),'cancelled_worker_reaped':True,
        'text':request['text'],'quality':'Listening and transcription acceptance still pending'}
(out/'local-runtime.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(record,ensure_ascii=True))
