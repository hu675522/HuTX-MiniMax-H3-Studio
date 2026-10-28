"""Build a source-only acceptance candidate, excluding runtime/user media/secrets."""
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]
FOLDERS=('web','locales','prompt_optimizer','speech_providers','docs')
EXTRAS=('LICENSE','README.md','requirements.txt','speech_requirements.txt','speech_build_constraints.txt','speech_runtime_lock.json')

def sources(root):
    files=list(root.glob('*.py'))+[root/name for name in EXTRAS]
    # Only the two attributed upstream examples; never include arbitrary user audio.
    files.extend(path for name in ('a.wav','b.wav','README.md','LICENSE-CosyVoice.txt')
                 if (path:=root/'assets/speech_voices'/name).is_file())
    for folder in FOLDERS:
        files.extend(p for p in (root/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.js','.css','.json','.md'))
    result=[]
    for path in sorted(set(files)):
        relative=path.relative_to(root)
        if path.is_symlink() or any(part.startswith('.') or part=='__pycache__' for part in relative.parts):continue
        if not path.resolve().is_relative_to(root.resolve()):raise ValueError('Package path escaped source root')
        result.append(path)
    return result

def build(root=ROOT):
    output=root/'.test-artifacts/release-stage6';output.mkdir(parents=True,exist_ok=True)
    archive=output/'HuTX-MiniMax-H3-Studio-stage6-awaiting-acceptance.zip'
    entries={};secret_pattern=re.compile(rb'\bsk-[A-Za-z0-9_-]{24,}\b|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')
    for path in sources(root):
        data=path.read_bytes()
        if secret_pattern.search(data):raise ValueError('Potential embedded secret in '+path.relative_to(root).as_posix())
        entries[path.relative_to(root).as_posix()]=data
    manifest={'status':'awaiting_manual_lip_sync_acceptance','plugin_version':'0.3.1',
        'intended_release':'0.4.0 only after acceptance','contains_models':False,'contains_credentials':False,
        'files':{name:hashlib.sha256(data).hexdigest() for name,data in entries.items()}}
    entries['ACCEPTANCE-MANIFEST.json']=json.dumps(manifest,ensure_ascii=False,indent=2).encode()
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as zipped:
        for name,data in entries.items():zipped.writestr('HuTX-MiniMax-H3-Studio/'+name,data)
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        for name,data in entries.items():assert zipped.read('HuTX-MiniMax-H3-Studio/'+name)==data
    result={'archive':str(archive),'files':len(entries),'bytes':archive.stat().st_size,
        'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'status':manifest['status']}
    (output/'package-verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
    return result

if __name__=='__main__':build()
