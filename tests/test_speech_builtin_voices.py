import pytest
from hutx_minimax_h3_testpkg import speech_local
from hutx_minimax_h3_testpkg.speech_service import SpeechService
from hutx_minimax_h3_testpkg.speech_validation import SpeechError
from hutx_minimax_h3_testpkg.speech_quality import check_reference_energy


@pytest.mark.parametrize('voice',['local:official-a','local:official-b'])
def test_builtin_reference_and_mock_adapter_flow(voice):
    pcm,text=speech_local.preset_reference(voice)
    pcm.validate();check_reference_energy(pcm)
    assert pcm.seconds>3
    seen=[]
    class Provider:
        version='unit-test'
        def synthesize(self,request,reference,cancel):
            seen.append((request,reference));return pcm
    service=SpeechService();service.real_providers={'local':Provider()}
    result,_=service.generate({'engine':'local','mode':'preset','voice':voice,'text':'新的测试台词','mock_demo':False})
    assert result.pcm==pcm and len(seen)==1
    request,reference=seen[0]
    assert request['text']=='新的测试台词' and request['mode']=='clone'
    assert reference==pcm and request['reference_text']==text


def test_builtin_catalog_survives_absent_user_bank(monkeypatch,tmp_path):
    monkeypatch.setattr(speech_local,'voice_root',lambda:tmp_path/'absent')
    voices=speech_local.local_voices()
    assert [v['id'] for v in voices]==['local:official-a','local:official-b']
    assert [v['name'] for v in voices]==['温柔女声','沉稳男声']


def test_builtin_missing_fails_safely(monkeypatch,tmp_path):
    monkeypatch.setattr(speech_local,'ROOT',tmp_path)
    assert speech_local.builtin_voices()==[]
    with pytest.raises(SpeechError):speech_local.preset_reference('local:official-a')
    with pytest.raises(SpeechError):speech_local.preset_reference('local:official-../../x')
