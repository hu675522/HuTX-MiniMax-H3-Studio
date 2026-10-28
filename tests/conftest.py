from __future__ import annotations

import sys
import types
from pathlib import Path


PACKAGE_NAME = "hutx_minimax_h3_testpkg"
PROJECT_ROOT = Path(__file__).resolve().parents[1]

if PACKAGE_NAME not in sys.modules:
    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(PROJECT_ROOT)]
    package.__package__ = PACKAGE_NAME
    sys.modules[PACKAGE_NAME] = package


import pytest


@pytest.fixture(autouse=True)
def isolated_fal_credentials(monkeypatch, tmp_path):
    from hutx_minimax_h3_testpkg import fal_credentials as credentials
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.setattr(credentials, "FAL_CREDENTIALS", credentials.FalCredentialStore(tmp_path / "fal_credentials.dat"))
    monkeypatch.setattr(credentials, "_known_secrets", set())
    from hutx_minimax_h3_testpkg.prompt_optimizer import credentials as optimizer_credentials
    from hutx_minimax_h3_testpkg.prompt_optimizer.config_schema import PROVIDER_ENV_KEYS
    for names in PROVIDER_ENV_KEYS.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(optimizer_credentials, "PROMPT_OPTIMIZER_CREDENTIALS",
                        optimizer_credentials.PromptOptimizerCredentialManager(tmp_path / "optimizer_credentials"))
    from hutx_minimax_h3_testpkg import speech_credentials, speech_local
    from hutx_minimax_h3_testpkg.speech_providers import bailian
    speech_store=speech_credentials.SpeechCredentials(tmp_path/'speech.dat')
    monkeypatch.delenv('HUTX_SPEECH_DASHSCOPE_API_KEY',raising=False)
    monkeypatch.setattr(speech_credentials,'SPEECH_CREDENTIALS',speech_store)
    monkeypatch.setattr(bailian,'SPEECH_CREDENTIALS',speech_store)
    monkeypatch.setattr(speech_local,'local_status',lambda:{'available':False,'notice':'isolated test'})
    monkeypatch.setattr(speech_local,'voice_root',lambda:tmp_path/'speech_voices')
    # Unit tests must inject providers/transport; never consume credits or load models.
    def forbidden(*args,**kwargs):raise AssertionError('Real speech runtime/network forbidden in pytest')
    monkeypatch.setattr(speech_local.LocalSpeechProvider,'synthesize',forbidden)
    monkeypatch.setattr(bailian.Transport,'request',forbidden)
    from hutx_minimax_h3_testpkg import speech_oss
    monkeypatch.setattr(speech_oss,'make_bucket',forbidden)
