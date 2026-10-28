"""Explicit operator download; never imported by the plugin or pytest."""
import hashlib
import urllib.request
from pathlib import Path

REVISION='b04bc07588601f7619b20efbb01cd1fa7278ccbc'
FILES={
    'en/tn/tagger.fst':'245e2dc9174cdd007a8e9e50f3339773d1adbbc7535b71cf67478dc1683cc3ec',
    'en/tn/verbalizer.fst':'03155c88f317b2795969e264c19f87faf98b9853d5ac631e419bacdc3b3ee15a',
    'zh/tn/tagger.fst':'cf341314c51f7ce59049f3b2c42f0ce8fd71e6d08d4d6969613aad384a5e2ae8',
    'zh/tn/verbalizer.fst':'5a13cd679dd54637d12d2bd1bd33ee2165d91c867e14468c93195af02256e5da',
}
root=Path(__file__).resolve().parents[1]/'.speech-runtime/models/wetext'
for name,sha in FILES.items():
    url=f'https://modelscope.cn/api/v1/models/pengzhendong/wetext/repo?Revision={REVISION}&FilePath={name}'
    with urllib.request.urlopen(url,timeout=120) as response: data=response.read()
    if hashlib.sha256(data).hexdigest()!=sha:raise RuntimeError('Text resource checksum mismatch')
    target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    print(name+' verified',flush=True)
