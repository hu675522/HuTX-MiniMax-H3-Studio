import asyncio
import json
import ssl

import aiohttp
import pytest

from hutx_minimax_h3_testpkg.prompt_optimizer.provider_errors import provider_http_error, provider_transport_error
from hutx_minimax_h3_testpkg.prompt_optimizer import provider_adapter
from hutx_minimax_h3_testpkg.prompt_optimizer.secrets import EPHEMERAL_SECRET_STORE
from .test_optimizer_runtime_serialization import backend

SECRET='TEST_DIAGNOSTIC_CREDENTIAL_SECRET_9876'


def test_new_bailian_default_keeps_explicit_workflow_models(backend):
    assert backend._normalize_config({'provider':'dashscope'})['model']=='qwen3-vl-plus'
    assert backend._normalize_config({'provider':'dashscope','model':'qwen-vl-max'})['model']=='qwen-vl-max'


@pytest.mark.parametrize('status,code,hint',[(404,'model_not_found','更换模型'),(401,'InvalidApiKey','鉴权失败'),
    (403,'Model.AccessDenied','没有调用权限'),(403,'Arrearage','余额'),(429,'Throttling','请求受限'),
    (400,'invalid_request_error','请求参数'),(400,'DataInspectionFailed','内容审核'),(503,'','暂时异常')])
def test_http_error_keeps_safe_status_code_and_actionable_hint(status,code,hint):
    error=provider_http_error(status,json.dumps({'error':{'code':code,'message':'echo '+SECRET}}))
    assert f'HTTP {status}' in str(error) and hint in str(error)
    if code:assert code in str(error)
    assert SECRET not in str(error)


@pytest.mark.parametrize('body',[json.dumps({'error':{'code':SECRET,'message':SECRET[:12]+' '+SECRET[-8:]}}),
    json.dumps({'error':{'code':[SECRET]}}),'<html>'+SECRET+'</html>','[1,2,3]'])
def test_arbitrary_response_details_are_never_published(body):
    error=provider_http_error(404,body)
    assert error.code=='' and 'HTTP 404' in str(error)
    assert SECRET not in str(error) and SECRET[:12] not in str(error) and SECRET[-8:] not in str(error)


@pytest.mark.parametrize('error,hint',[(asyncio.TimeoutError(SECRET),'超时'),(ssl.SSLError(SECRET),'证书'),
    (aiohttp.ClientConnectionError(SECRET),'无法连接'),(ValueError(SECRET),'JSON')])
def test_transport_diagnostics_do_not_forward_raw_exception(error,hint):
    message=str(provider_transport_error(error))
    assert hint in message and SECRET not in message


def test_actual_request_path_preserves_model_error_without_keys_or_silent_retry(backend,monkeypatch,caplog):
    calls=[]
    class Response:
        status=404
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def text(self):return json.dumps({'error':{'code':'model_not_found','message':SECRET+' '+SECRET[:12]+' '+SECRET[-8:]}})
    class Session:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def post(self,url,headers,json):
            assert headers['Authorization']=='Bearer '+SECRET
            calls.append(json['model']);return Response()
    monkeypatch.setattr(backend.aiohttp,'ClientSession',Session)
    reference=EPHEMERAL_SECRET_STORE.put('dashscope',SECRET)
    config={'mode':'api','provider':'dashscope','api_url':'https://mock.invalid/v1','protocol':'openai',
            'model':'qwen-vl-max','read_media':False,'credential_ref':reference}
    with pytest.raises(RuntimeError,match='HTTP 404.*model_not_found.*更换模型') as failure:
        asyncio.run(provider_adapter.request_optimized_prompt(config,{'prompt':'Test','media':[]}))
    assert calls==['qwen-vl-max']  # Existing explicit model choices remain untouched.
    output=str(failure.value)+caplog.text
    for value in (SECRET,SECRET[:12],SECRET[-8:],reference):assert value not in output
    assert 'Traceback' in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
