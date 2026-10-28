"""Runs ONLY inside the isolated CosyVoice Python process; no listening port."""
import json
import os
import sys
from pathlib import Path


def deny_network(event, args):
    if event in ('socket.connect', 'socket.getaddrinfo', 'socket.sendto'):
        raise RuntimeError('Local speech worker does not allow network access')


def reference_transcript(request,samples,rate,model):
    if request.get('reference_text','').strip():return request['reference_text']
    from _hutx_worker.speech_errors import SpeechFailure
    import hashlib
    weights=model.parent/'quality/base.pt'
    if not weights.is_file() or hashlib.sha256(weights.read_bytes()).hexdigest()!='ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e':
        raise SpeechFailure('reference_transcript')
    import torch
    import torchaudio
    import whisper
    audio=torch.from_numpy(samples)
    if audio.ndim==2:audio=audio.mean(dim=1)
    mono=torchaudio.functional.resample(audio,rate,16000).numpy()
    recognizer=whisper.load_model(str(weights),device='cpu')
    try:
        result=recognizer.transcribe(mono,fp16=False,temperature=0,condition_on_previous_text=False)
        text=result.get('text','').strip()
        if not text or len(text)>4000:raise SpeechFailure('reference_transcript')
        return text
    except Exception:raise SpeechFailure('reference_transcript') from None
    finally:del recognizer


def main():
    code, model, temporary = map(Path, sys.argv[1:4])
    sys.addaudithook(deny_network)
    sys.path[:0] = [str(code), str(code/'third_party/Matcha-TTS')]
    os.environ['HF_HUB_OFFLINE']='1'
    os.environ['TRANSFORMERS_OFFLINE']='1'
    import torch
    import soundfile as sf
    import wetext.wetext as text_frontend
    # WeText defaults to an online snapshot lookup even with HF offline enabled.
    # Bind this worker's lookup to the explicitly installed, pinned local FSTs.
    text_resources=model.parent/'wetext'
    for language in ('zh','en'):
        for name in ('tagger.fst','verbalizer.fst'):
            if not (text_resources/language/'tn'/name).is_file():
                raise RuntimeError('Missing offline text normalization resources')
    text_frontend.snapshot_download=lambda *args, **kwargs: str(text_resources)
    from cosyvoice.cli.cosyvoice import CosyVoice3
    request=json.loads((temporary/'request.json').read_text(encoding='utf-8'))
    import types
    package=types.ModuleType('_hutx_worker');package.__path__=[str(Path(__file__).resolve().parent)]
    sys.modules[package.__name__]=package
    from _hutx_worker.speech_quality import check_speech_onnx
    from _hutx_worker.speech_errors import SpeechFailure
    samples,rate=sf.read(str(temporary/'reference.wav'),dtype='float32')
    try:
        check_speech_onnx(samples,rate,model.parent/'quality/silero_vad.onnx')
        try:request['reference_text']=reference_transcript(request,samples,rate,model)
        except Exception:raise SpeechFailure('reference_transcript') from None
    except SpeechFailure as exc:
        (temporary/'error.json').write_text(json.dumps({'code':exc.code}),encoding='utf-8')
        return
    voice=CosyVoice3(str(model),load_trt=False,load_vllm=False,fp16=torch.cuda.is_available())
    if voice.frontend.text_frontend != 'wetext':
        raise RuntimeError('Offline text normalization failed to initialize')
    text='You are a helpful assistant.<|endofprompt|>'+request['reference_text']
    parts=[]
    with torch.inference_mode():
        for output in voice.inference_zero_shot(request['text'],text,str(temporary/'reference.wav'),stream=False,speed=request['speed']):
            parts.append(output['tts_speech'].detach().cpu())
    if not parts:raise RuntimeError('No speech output')
    audio=torch.cat(parts,dim=-1)
    if not torch.isfinite(audio).all():raise RuntimeError('Invalid waveform')
    sf.write(str(temporary/'output.wav'),audio.squeeze(0).numpy(),voice.sample_rate,subtype='PCM_16')


if __name__=='__main__':
    main()
