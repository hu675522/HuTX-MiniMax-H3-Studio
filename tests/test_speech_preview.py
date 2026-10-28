import asyncio
import json
import subprocess
from pathlib import Path
import pytest
from tests.test_speech_bridge import bridge_env
from hutx_minimax_h3_testpkg.speech_service import SpeechService
from hutx_minimax_h3_testpkg.speech_snapshot import snapshot_summary,load_snapshot
from hutx_minimax_h3_testpkg.speech_validation import SpeechError


def adopted():
    service=SpeechService()
    result,_=service.generate({'engine':'local','mode':'preset','voice':'local:demo-a','mock_demo':True,'text':'预览测试'})
    ref=service.adopt(result.audio_id)
    service.cache.clear()
    return result,ref


def test_preview_survives_cache_clear_with_only_safe_metadata(bridge_env):
    result,ref=adopted()
    data=snapshot_summary(ref)
    assert set(data)=={'audio_file','duration_seconds'}
    assert data['duration_seconds']==result.pcm.seconds
    assert (bridge_env/data['audio_file']).is_file()
    with pytest.raises(SpeechError):load_snapshot(ref,'changed-input-fingerprint')


@pytest.mark.parametrize('bad', ['../private.json', 'hutx-speech/adopted/'+'a'*64+'.json', 'C:/private.json'])
def test_preview_rejects_arbitrary_or_missing_file(bridge_env,bad):
    with pytest.raises(SpeechError):snapshot_summary(bad)


def test_preview_checks_audio_integrity(bridge_env):
    _,ref=adopted();data=snapshot_summary(ref)
    (bridge_env/data['audio_file']).write_bytes(b'corrupt')
    with pytest.raises(SpeechError):snapshot_summary(ref)


def test_preview_route_secret_free_and_strict(bridge_env):
    from hutx_minimax_h3_testpkg.speech_routes import speech_adopted_preview
    _,ref=adopted()
    class Request:
        def __init__(self,query):self.query=query
    good=asyncio.run(speech_adopted_preview(Request({'file':ref})))
    assert good.status==200 and good.headers['Cache-Control']=='no-store'
    assert set(json.loads(good.body))=={'audio_file','duration_seconds'}
    bad=asyncio.run(speech_adopted_preview(Request({'file':ref,'key':'TEST_SECRET'})))
    assert bad.status==400 and b'TEST_SECRET' not in bad.body


def test_driver_projection_canonical_and_read_only():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','tests/frontend_local_driver_fixture.mjs'],cwd=root,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
