"""Operator-only offline ASR verification using the existing accepted fixture."""
import sys,types,json
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from speech_worker import reference_transcript,deny_network
sys.addaudithook(deny_network)
package=types.ModuleType('_hutx_worker');package.__path__=[str(root)];sys.modules[package.__name__]=package
import soundfile as sf
samples,rate=sf.read(root/'.test-artifacts/speech-stage34/official-reference-pcm16.wav',dtype='float32')
text=reference_transcript({'reference_text':''},samples,rate,root/'.speech-runtime/models/Fun-CosyVoice3-0.5B-2512')
record={'offline':True,'provided_reference_text':False,'recognized_nonempty':bool(text),'transcript':text}
(root/'.test-artifacts/speech-stage34/automatic-reference-transcript.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(record,ensure_ascii=True))
