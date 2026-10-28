import importlib.util
import sys
import types
from pathlib import Path
import numpy as np
import pytest
from hutx_minimax_h3_testpkg import speech_errors

@pytest.fixture
def worker(monkeypatch):
    path=Path(__file__).resolve().parents[1]/'speech_worker.py'
    spec=importlib.util.spec_from_file_location('reference_worker_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules,'_hutx_worker',types.ModuleType('_hutx_worker'))
    monkeypatch.setitem(sys.modules,'_hutx_worker.speech_errors',speech_errors)
    return module

def test_old_reference_text_still_used_without_asr(worker):
    assert worker.reference_transcript({'reference_text':'原工作流文本'},None,None,None)=='原工作流文本'

def test_missing_asr_fails_with_fixed_error(worker,tmp_path):
    with pytest.raises(speech_errors.SpeechFailure) as error:worker.reference_transcript({},None,16000,tmp_path/'model')
    assert error.value.code=='reference_transcript'

@pytest.mark.parametrize('transcript',['识别的参考音频内容','', 'x'*4001])
def test_automatic_transcript_uses_local_cpu_model(worker,tmp_path,monkeypatch,transcript):
    import hashlib
    quality=tmp_path/'quality';quality.mkdir();(quality/'base.pt').write_bytes(b'mock')
    monkeypatch.setattr(hashlib,'sha256',lambda data:types.SimpleNamespace(hexdigest=lambda:'ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e'))
    calls=[]
    def load(path,device):
        calls.append((path,device));return types.SimpleNamespace(transcribe=lambda *a,**kw:{'text':transcript})
    monkeypatch.setitem(sys.modules,'whisper',types.SimpleNamespace(load_model=load))
    monkeypatch.setitem(sys.modules,'torchaudio',types.SimpleNamespace(functional=types.SimpleNamespace(resample=lambda tensor,*a:tensor)))
    if transcript and len(transcript)<=4000:
        assert worker.reference_transcript({},np.zeros((100,2),np.float32),16000,tmp_path/'model')==transcript
    else:
        with pytest.raises(speech_errors.SpeechFailure):worker.reference_transcript({},np.zeros(100,np.float32),16000,tmp_path/'model')
    assert calls==[(str(quality/'base.pt'),'cpu')]
