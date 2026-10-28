"""Provider-bound optimizer persistence, isolated from Fal credential data."""
from __future__ import annotations

import base64
import json
import os
import threading
from pathlib import Path

from ..fal_credentials import WindowsDPAPI
from . import secrets
from .config_schema import PROVIDER_ENV_KEYS
from . import config_schema
from .secrets import OptimizerCredentialError


class PersistedCredentialUnavailable(OptimizerCredentialError):
    pass


def provider_id(provider):
    value = str(provider or "").strip().lower()
    if value == "openai-compatible":
        value = "custom"
    if value not in PROVIDER_ENV_KEYS:
        raise OptimizerCredentialError("Unsupported prompt optimizer provider.")
    return value


def credential_directory():
    import folder_paths
    return Path(folder_paths.get_user_directory()) / "default" / "HuTX-MiniMax-H3-Studio" / "prompt_optimizer_credentials"


class PromptOptimizerCredentialManager:
    def __init__(self, directory=credential_directory, cipher=None):
        self.directory = directory
        self.cipher = cipher or WindowsDPAPI()
        self.lock = threading.RLock()

    def path(self, provider):
        root = self.directory() if callable(self.directory) else self.directory
        return Path(root) / (provider_id(provider) + ".dat")

    def save(self, provider, key):
        provider = provider_id(provider)
        if not isinstance(key, str) or not key.strip() or len(key) > 8192:
            raise OptimizerCredentialError("请先输入 API Key")
        if not self.cipher.supported:
            raise OptimizerCredentialError("当前系统暂不支持本机安全持久化。")
        with self.lock:
            try:
                # Bind the provider inside the protected envelope too: moving
                # an encrypted file to another provider cannot rebind its key.
                payload = json.dumps({"provider": provider, "key": key.strip()}).encode("utf-8")
                blob = self.cipher.encrypt(payload)
                document = {"version": 1, "provider": provider,
                            "encrypted_blob": base64.b64encode(blob).decode("ascii"),
                            "metadata": {"protection": "DPAPI", "scope": "CurrentUser"}}
                path = self.path(provider)
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".tmp")
                try:
                    temporary.write_text(json.dumps(document), encoding="utf-8")
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
            except Exception:
                raise OptimizerCredentialError("无法安全保存本机凭证，请重新配置。") from None

    def persisted(self, provider):
        provider = provider_id(provider)
        try:
            path = self.path(provider)
        except (ImportError, AttributeError):
            return ""
        if not path.exists():
            return ""
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if doc["version"] != 1 or doc["provider"] != provider or not self.cipher.supported:
                raise ValueError()
            data = json.loads(self.cipher.decrypt(base64.b64decode(doc["encrypted_blob"], validate=True)))
            if data["provider"] != provider or not isinstance(data["key"], str) or not data["key"].strip():
                raise ValueError()
            return data["key"]
        except Exception:
            raise PersistedCredentialUnavailable("本机凭证不可用，请重新配置") from None

    def resolve(self, provider, credential_ref=None):
        provider = provider_id(provider)
        env = config_schema._environment_api_key(provider)
        if env:
            return env
        # An explicitly supplied invalid reference still fails closed; no
        # silent replacement of an expired or cross-provider session.
        if credential_ref:
            return secrets.EPHEMERAL_SECRET_STORE.resolve(credential_ref, provider)
        with self.lock:
            return self.persisted(provider)

    def status(self, provider, credential_ref=None, *, ignore_unavailable=False):
        provider = provider_id(provider)
        environment = bool(config_schema._environment_api_key(provider))
        session = False
        if credential_ref:
            try:
                session = bool(secrets.EPHEMERAL_SECRET_STORE.resolve(credential_ref, provider))
            except OptimizerCredentialError:
                pass
        try:
            with self.lock:
                persisted = bool(self.persisted(provider))
        except PersistedCredentialUnavailable:
            if not ignore_unavailable:
                raise
            persisted = False
        source = "environment" if environment else "session" if session else "persisted" if persisted else "none"
        return {"provider": provider, "configured": source != "none", "active_source": source,
                "environment_configured": environment, "session_configured": session,
                "persisted_configured": persisted, "persistence_supported": self.cipher.supported}

    def delete(self, provider):
        with self.lock:
            try:
                self.path(provider).unlink(missing_ok=True)
            except Exception:
                raise OptimizerCredentialError("无法删除本机凭证。") from None


PROMPT_OPTIMIZER_CREDENTIALS = PromptOptimizerCredentialManager()


def resolve_prompt_optimizer_api_key(provider, credential_ref=None):
    return PROMPT_OPTIMIZER_CREDENTIALS.resolve(provider, credential_ref)


async def credential_route(request):
    from aiohttp import web
    try:
        payload = await request.json() if request.method == "POST" else request.query
        provider = provider_id(payload.get("provider"))
        # Reference travels in a header, never a URL/query or a status response.
        reference = request.headers.get("X-HuTX-Optimizer-Reference")
        if request.method == "POST":
            PROMPT_OPTIMIZER_CREDENTIALS.save(provider, payload.get("api_key"))
            payload.clear()
        elif request.method == "DELETE":
            PROMPT_OPTIMIZER_CREDENTIALS.delete(provider)
        try:
            status = PROMPT_OPTIMIZER_CREDENTIALS.status(provider, reference)
            code = 200
        except PersistedCredentialUnavailable:
            status = PROMPT_OPTIMIZER_CREDENTIALS.status(provider, reference, ignore_unavailable=True)
            code = 409
        return web.json_response(status, status=code, headers={"Cache-Control": "no-store"})
    except Exception:
        return web.json_response({"error": "凭证操作失败，请检查平台及本机安全存储支持。"}, status=400)
