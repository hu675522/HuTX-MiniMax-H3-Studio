"""Operator-only official quality assets. No model downloads at inference time."""
import hashlib
import urllib.request
from pathlib import Path

root=Path(__file__).resolve().parents[1]/'.speech-runtime/models/quality'
root.mkdir(parents=True,exist_ok=True)
assets=[
 ('silero_vad.onnx','https://raw.githubusercontent.com/snakers4/silero-vad/867c2aa692646a1f1de3e94a15c9dd9f614c0acb/src/silero_vad/data/silero_vad.onnx','1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3'),
 ('base.pt','https://openaipublic.azureedge.net/main/whisper/models/ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e/base.pt','ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e')]
for name,url,sha in assets:
    path=root/name
    if path.exists() and sha and hashlib.sha256(path.read_bytes()).hexdigest()==sha:continue
    with urllib.request.urlopen(url,timeout=180) as response:data=response.read()
    digest=hashlib.sha256(data).hexdigest()
    if sha and digest!=sha:raise RuntimeError('Quality model checksum mismatch')
    path.write_bytes(data)
    print(name+' '+str(len(data))+' '+digest,flush=True)
