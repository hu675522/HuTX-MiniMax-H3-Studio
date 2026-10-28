"""Safe provider diagnostics: never copy HTTP bodies or arbitrary error strings."""
from __future__ import annotations

import asyncio
import json
import ssl

import aiohttp

_CODE_KIND = {
    'model_not_found':'model', 'ModelNotFound':'model',
    'invalid_api_key':'auth', 'InvalidApiKey':'auth', 'AuthenticationError':'auth',
    'Arrearage':'billing', 'InsufficientBalance':'billing', 'insufficient_quota':'billing',
    'AccessDenied.Unpurchased':'billing',
    'Model.AccessDenied':'permission', 'App.AccessDenied':'permission', 'AccessDenied':'permission',
    'Throttling':'rate', 'Throttling.RateQuota':'rate', 'rate_limit_exceeded':'rate',
    'InvalidParameter':'parameter', 'invalid_parameter':'parameter', 'invalid_request_error':'parameter',
    'DataInspectionFailed':'content', 'InputDataInspectionFailed':'content', 'OutputDataInspectionFailed':'content',
}
_HINTS = {
    'model':'所选模型不存在或当前账号不可用，请更换模型，并核对接口地域和模型权限。',
    'auth':'鉴权失败，请核对 API Key、接口地域及套餐专用地址是否匹配。',
    'billing':'账户余额、额度或服务开通状态异常，请检查服务商控制台。',
    'permission':'当前凭证没有调用权限，请检查模型和业务空间授权。',
    'rate':'请求受限，请检查服务商限流或额度，稍后重试。',
    'parameter':'请求参数不被模型接受，请检查模型对视觉输入及输出 Token 上限的支持。',
    'content':'服务商内容审核未通过，请检查提示词和参考素材。',
    'server':'服务商暂时异常，请稍后重试。',
    'timeout':'模型请求超时，请检查网络或减少参考素材后重试。',
    'tls':'HTTPS 证书校验失败，请检查系统时间、证书和代理设置。',
    'connection':'无法连接模型服务，请检查网络、代理和接口地址。',
    'response':'服务商返回了无效的 JSON 响应，请检查接口地址或代理。',
    'unknown':'模型请求失败，请检查服务商配置。',
}


class ProviderRequestError(RuntimeError):
    def __init__(self, kind='unknown', *, status=None, code=''):
        self.status = status if type(status) is int and 100 <= status <= 599 else None
        self.code = code if isinstance(code, str) and code in _CODE_KIND else ''
        self.kind = kind if kind in _HINTS else 'unknown'
        details = [f'HTTP {self.status}'] if self.status else []
        if self.code: details.append(self.code)
        suffix = f" ({'; '.join(details)})" if details else ''
        super().__init__('LLM provider request failed' + suffix + '：' + _HINTS[self.kind])


def provider_http_error(status, body):
    code = ''
    try:
        # Only an allowlisted machine code leaves this boundary, never messages.
        data = json.loads(body[:65536]) if isinstance(body, str) else {}
        error = data.get('error', data) if isinstance(data, dict) else {}
        raw = error.get('code') if isinstance(error, dict) else None
        if isinstance(raw, str) and raw in _CODE_KIND: code = raw
    except (ValueError, TypeError):
        pass
    kind = _CODE_KIND.get(code)
    if kind is None:
        kind = {400:'parameter',401:'auth',402:'billing',403:'permission',404:'model',429:'rate'}.get(status,'server' if type(status) is int and status>=500 else 'unknown')
    return ProviderRequestError(kind,status=status,code=code)


def provider_transport_error(error):
    if isinstance(error, (asyncio.TimeoutError, aiohttp.ServerTimeoutError)):kind='timeout'
    elif isinstance(error, (aiohttp.ClientConnectorCertificateError,aiohttp.ClientSSLError,ssl.SSLError)):kind='tls'
    elif isinstance(error, aiohttp.ClientError):kind='connection'
    elif isinstance(error, ValueError):kind='response'
    else:kind='unknown'
    return ProviderRequestError(kind)
