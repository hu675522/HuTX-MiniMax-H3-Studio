"""Operator-only offline reference/output VAD and transcript acceptance."""
import importlib
import json
import re
import sys
import types
from pathlib import Path
import numpy as np
import soundfile as sf
import torch
import torchaudio
import whisper

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from speech_worker import deny_network
sys.addaudithook(deny_network)
package=types.ModuleType('hutx_quality');package.__path__=[str(root)];sys.modules[package.__name__]=package
quality=importlib.import_module(package.__name__+'.speech_quality')
errors=importlib.import_module(package.__name__+'.speech_errors')
out=root/'.test-artifacts/speech-stage34';assets=root/'.speech-runtime/models/quality'
audio,rate=sf.read(out/'local-cosyvoice.wav',dtype='float32')
reference,reference_rate=sf.read(out/'official-reference-pcm16.wav',dtype='float32')
vad={}
for name,data,sr in [('reference',reference,reference_rate),('generated',audio,rate)]:
    vad[name]=quality.check_speech_onnx(data,sr,assets/'silero_vad.onnx')
for name,data in [('silence',np.zeros(16000*3,np.float32)),
                  ('tone',(.1*np.sin(np.arange(16000*3)*2*np.pi*440/16000)).astype(np.float32))]:
    try:quality.check_speech_onnx(data,16000,assets/'silero_vad.onnx');raise AssertionError('Non-speech accepted')
    except errors.SpeechFailure:vad[name]='rejected'
model=whisper.load_model(str(assets/'base.pt'),device='cpu')
mono=torchaudio.functional.resample(torch.from_numpy(audio),rate,16000).numpy()
result=model.transcribe(mono,language='zh',fp16=False,temperature=0,condition_on_previous_text=False)
expected='很高兴见到你。今天我们一起测试本地声音克隆。'
normalize=lambda text: re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]','',text)
record={'vad':vad,'expected':expected,'transcript':result['text'],
        'exact_transcript_match':normalize(result['text'])==normalize(expected),
        'listening_acceptance':'User confirmed 2026-09-12', 'offline':True}
(out/'quality-acceptance.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(record,ensure_ascii=True))
