"""Fal credentials: environment, process session, or Windows Current User DPAPI."""
from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import threading
from pathlib import Path


class FalCredentialError(RuntimeError):
    pass


class WindowsDPAPI:
    @property
    def supported(self):
        return os.name == "nt"

    def _crypt(self, data: bytes, decrypt: bool) -> bytes:
        if not self.supported:
            raise FalCredentialError("当前系统暂不支持本机持久安全存储；请使用环境变量或会话凭证。")
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

        crypt = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        buffer = ctypes.create_string_buffer(data)
        source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        target = Blob()
        fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
        fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        fn.restype = wintypes.BOOL
        # CRYPTPROTECT_UI_FORBIDDEN only; deliberately no LOCAL_MACHINE flag.
        if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
            raise FalCredentialError("本机 Fal 凭证无法解密或保存，请在当前 Windows 用户下重新配置。")
        try:
            return ctypes.string_at(target.data, target.size)
        finally:
            kernel.LocalFree(target.data)
            ctypes.memset(buffer, 0, len(buffer))

    def encrypt(self, data):
        return self._crypt(data, False)

    def decrypt(self, data):
        return self._crypt(data, True)


def credential_path() -> Path:
    import folder_paths
    return Path(folder_paths.get_user_directory()) / "default" / "HuTX-MiniMax-H3-Studio" / "fal_credentials.dat"


_known_secrets: set[str] = set()
_redaction_lock = threading.RLock()


def _remember(key):
    with _redaction_lock:
        _known_secrets.add(key)
    return key


def redact_fal_secrets(value) -> str:
    text = str(value)
    with _redaction_lock:
        keys = _known_secrets | {os.environ.get("FAL_KEY", "")}
    for key in sorted(filter(None, keys), key=len, reverse=True):
        text = text.replace(key, "[REDACTED]")
    return text


class FalLogFilter(logging.Filter):
    def filter(self, record):
        record.msg = redact_fal_secrets(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.msg += "\n" + redact_fal_secrets(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
            record.exc_text = None
        return True


class FalCredentialStore:
    def __init__(self, path=credential_path, cipher=None):
        self._path = path
        self._cipher = cipher or WindowsDPAPI()
        self._session = ""
        self._lock = threading.RLock()

    def path(self):
        return Path(self._path() if callable(self._path) else self._path)

    def save(self, key, storage="persisted"):
        if not isinstance(key, str) or not key.strip() or len(key) > 8192:
            raise FalCredentialError("请输入有效的 FAL_KEY。")
        if storage not in {"session", "persisted"}:
            raise FalCredentialError("Unknown credential storage mode.")
        key = _remember(key.strip())
        with self._lock:
            if storage == "session":
                self._session = key
                return
            encrypted = self._cipher.encrypt(key.encode("utf-8"))
            document = {"version": 1, "encrypted_blob": base64.b64encode(encrypted).decode("ascii"),
                        "metadata": {"protection": "DPAPI", "scope": "CurrentUser"}}
            try:
                path = self.path()
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps(document), encoding="utf-8")
                os.replace(temporary, path)
            except Exception:
                raise FalCredentialError("无法保存本机 Fal 凭证。") from None

    def _persisted(self):
        try:
            path = self.path()
        except (ImportError, AttributeError):
            return ""
        if not path.exists():
            return ""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["version"] != 1:
                raise ValueError()
            key = self._cipher.decrypt(base64.b64decode(data["encrypted_blob"], validate=True)).decode("utf-8")
            if not key:
                raise ValueError()
            return _remember(key)
        except Exception:
            raise FalCredentialError("本机 Fal 凭证无法解密，请在当前 Windows 用户下重新配置。") from None

    def resolve(self):
        with self._lock:
            env = os.environ.get("FAL_KEY", "").strip()
            if env:
                return _remember(env), "environment"
            if self._session:
                return self._session, "session"
            key = self._persisted()
            if key:
                return key, "persisted"
        raise FalCredentialError("请配置 FAL_KEY 环境变量或 Fal API 凭证。")

    def status(self):
        with self._lock:
            environment = bool(os.environ.get("FAL_KEY", "").strip())
            session = bool(self._session)
            try:
                persisted = bool(self._persisted())
            except (FalCredentialError, OSError):
                persisted = False
            source = "environment" if environment else "session" if session else "persisted" if persisted else "none"
            return {"configured": source != "none", "active_source": source,
                    "environment_configured": environment, "session_configured": session,
                    "persisted_configured": persisted, "persistence_supported": bool(self._cipher.supported)}

    def delete_persisted(self):
        with self._lock:
            try:
                self.path().unlink(missing_ok=True)
            except Exception:
                raise FalCredentialError("无法删除本机 Fal 凭证。") from None


FAL_CREDENTIALS = FalCredentialStore()


def resolve_fal_api_key():
    return FAL_CREDENTIALS.resolve()[0]


async def fal_credential_get(request):
    from aiohttp import web
    return web.json_response(FAL_CREDENTIALS.status(), headers={"Cache-Control": "no-store"})


async def fal_credential_save(request):
    from aiohttp import web
    data = {}
    try:
        if request.content_type != "application/json":
            raise FalCredentialError("Expected application/json.")
        data = await request.json()
        if not isinstance(data, dict):
            raise FalCredentialError("Invalid credential request.")
        FAL_CREDENTIALS.save(data.pop("key", None), data.get("storage", "persisted"))
        return await fal_credential_get(request)
    except Exception as exc:
        message = str(exc) if isinstance(exc, FalCredentialError) else "无法保存 Fal 凭证。"
        return web.json_response({"error": redact_fal_secrets(message)}, status=400, headers={"Cache-Control": "no-store"})
    finally:
        if isinstance(data, dict):
            data.clear()


async def fal_credential_delete(request):
    from aiohttp import web
    try:
        FAL_CREDENTIALS.delete_persisted()
        return await fal_credential_get(request)
    except Exception:
        return web.json_response({"error": "无法删除本机 Fal 凭证。"}, status=400)


def register_fal_credential_routes():
    from server import PromptServer
    instance = PromptServer.instance
    if getattr(instance, "_hutx_fal_credential_routes", None) is instance.routes:
        return
    route = "/hutx/minimax-h3/fal-credential"
    instance.routes.get(route)(fal_credential_get)
    instance.routes.post(route)(fal_credential_save)
    instance.routes.delete(route)(fal_credential_delete)
    instance._hutx_fal_credential_routes = instance.routes
