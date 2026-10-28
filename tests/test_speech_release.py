import importlib.util
from pathlib import Path
import json
import zipfile

def test_candidate_archive_excludes_credentials_runtime_and_user_media(tmp_path):
    path=Path(__file__).with_name('package_speech_candidate.py')
    spec=importlib.util.spec_from_file_location('speech_package_fixture',path)
    package=importlib.util.module_from_spec(spec);spec.loader.exec_module(package)
    for name in package.EXTRAS:(tmp_path/name).write_text('safe',encoding='utf-8')
    (tmp_path/'nodes.py').write_text('# runtime',encoding='utf-8')
    for directory in ('.speech-runtime','input','user','web','docs','prompt_optimizer'):(tmp_path/directory).mkdir()
    (tmp_path/'.speech-runtime/fal_credentials.dat').write_bytes(b'TEST_SECRET')
    (tmp_path/'user/key.json').write_text('TEST_SECRET')
    (tmp_path/'input/private.wav').write_bytes(b'TEST_PRIVATE_AUDIO')
    (tmp_path/'web/panel.js').write_text('// public')
    result=package.build(tmp_path)
    with zipfile.ZipFile(result['archive']) as archive:
        contents=b''.join(archive.read(name) for name in archive.namelist())
        assert b'TEST_SECRET' not in contents and b'TEST_PRIVATE_AUDIO' not in contents
        manifest=json.loads(archive.read('HuTX-MiniMax-H3-Studio/ACCEPTANCE-MANIFEST.json'))
        assert manifest['status']=='awaiting_manual_lip_sync_acceptance'
        assert 'nodes.py' in manifest['files'] and 'web/panel.js' in manifest['files']
