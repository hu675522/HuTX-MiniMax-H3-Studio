import asyncio
import json
from types import SimpleNamespace

import aiohttp
import pytest

from hutx_minimax_h3_testpkg.prompt_optimizer import model_catalog as catalog, credentials, config_schema
from hutx_minimax_h3_testpkg.prompt_optimizer.secrets import EPHEMERAL_SECRET_STORE
from .test_optimizer_runtime_serialization import backend

KEY = 'TEST_CATALOG_SECRET_987654321'


def transport(monkeypatch, responses):
    calls = []
    class Response:
        def __init__(self, status, data):
            self.status = status
            self.raw = data if isinstance(data, bytes) else json.dumps(data).encode()
            self.content = self
        async def iter_chunked(self, size):
            for start in range(0,len(self.raw),size): yield self.raw[start:start+size]
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    class Session:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            item = responses.pop(0)
            if isinstance(item, Exception): raise item
            return Response(*item)
    monkeypatch.setattr(catalog.aiohttp, 'ClientSession', Session)
    return calls


def request(provider='dashscope', reference='', **extra):
    return SimpleNamespace(query={'provider':provider, **extra}, headers={'X-HuTX-Optimizer-Reference':reference})


def test_normalization_keeps_exact_ids_filters_non_chat_and_reports_known_vision():
    data = {'data':[{'id':'qwen3-vl-plus'}, {'id':'qwen3-vl-plus'}, {'id':'text-embedding-v3'},
                    {'id':'bad\nname'}, {'id':'a'*241}, {'id':KEY}, {'id':'text-model','architecture':{'input_modalities':['text']}},
                    {'id':'vision','architecture':{'input_modalities':['text','image'],'output_modalities':['text']}},
                    {'id':'image-generator','architecture':{'output_modalities':['image']}}, None]}
    rows = catalog.normalize_models(data,'openrouter')
    assert len(rows)==4
    assert next(row for row in rows if row['id']=='qwen3-vl-plus')['vision'] is None
    assert next(row for row in rows if row['id']=='vision')['vision'] is True
    assert next(row for row in rows if row['id']=='text-model')['vision'] is False


@pytest.mark.parametrize('provider',list(catalog.ENDPOINTS))
def test_official_endpoint_auth_and_no_redirects(backend,monkeypatch,provider):
    payload = {'models':[{'name':'models/gemini-2.5-flash','supportedGenerationMethods':['generateContent']}]} if provider=='gemini' else {'data':[{'id':'qwen3-vl-plus'}]}
    calls = transport(monkeypatch,[(200,payload)])
    reference = EPHEMERAL_SECRET_STORE.put(provider,KEY)
    result = asyncio.run(catalog.api_models_route(request(provider,reference)))
    assert result.status==200 and result.headers['Cache-Control']=='no-store'
    assert KEY not in result.text and reference not in result.text
    url, options = calls[0]
    assert url==catalog.ENDPOINTS[provider] and options['allow_redirects'] is False
    assert options['headers']==({'x-goog-api-key':KEY} if provider=='gemini' else {'Authorization':'Bearer '+KEY})
    assert KEY not in url and KEY not in json.dumps(options['params'])


def test_gemini_pagination_and_supported_generation_methods(backend,monkeypatch):
    calls = transport(monkeypatch,[(200,{'models':[{'name':'models/a','supportedGenerationMethods':['generateContent']},
             {'name':'models/embed','supportedGenerationMethods':['embedContent']},{'name':'models/bad','supportedGenerationMethods':None}], 'nextPageToken':'page2'}),
          (200,{'models':[{'name':'models/b','supportedGenerationMethods':['generateContent']}], 'nextPageToken':'page2'})])
    rows = asyncio.run(catalog.fetch_api_models('gemini',KEY))
    assert [row['id'] for row in rows]==['a','b']
    assert len(calls)==2 and calls[1][1]['params']['pageToken']=='page2'


def test_credential_priority_and_expired_reference_no_network(backend,monkeypatch):
    credentials.PROMPT_OPTIMIZER_CREDENTIALS.save('dashscope',KEY)
    reference = EPHEMERAL_SECRET_STORE.put('dashscope','TEST_SESSION_CATALOG_KEY')
    monkeypatch.setenv('DASHSCOPE_API_KEY','TEST_ENV_CATALOG_KEY')
    monkeypatch.setattr(config_schema,'_environment_api_key',lambda provider:'TEST_ENV_CATALOG_KEY' if provider=='dashscope' else '')
    calls = transport(monkeypatch,[(200,{'data':[{'id':'qwen3-vl-plus'}]})])
    assert asyncio.run(catalog.api_models_route(request(reference=reference))).status==200
    assert calls[0][1]['headers']['Authorization']=='Bearer TEST_ENV_CATALOG_KEY'
    monkeypatch.delenv('DASHSCOPE_API_KEY')
    monkeypatch.setattr(config_schema,'_environment_api_key',lambda provider:'')
    EPHEMERAL_SECRET_STORE.clear()
    assert asyncio.run(catalog.api_models_route(request(reference=reference))).status==400
    assert len(calls)==1


@pytest.mark.parametrize('provider,extra',[('custom',{}),('dashscope',{}),('dashscope',{'api_key':KEY}),('https://evil.invalid',{})])
def test_missing_key_unknown_provider_and_query_secrets_never_call_transport(backend,provider,extra):
    response = asyncio.run(catalog.api_models_route(request(provider,**extra)))
    assert response.status==400 and KEY not in response.text


@pytest.mark.parametrize('item,hint',[( (401,{'error':{'message':KEY}}),'鉴权失败'),
    ((404,{'error':{'code':'model_not_found','message':KEY}}),'HTTP 404'),
    ((200,b'not JSON '+KEY.encode()),'JSON'), ((200,{'data':[]}), 'JSON'),
    ((200,b'x'*(catalog.MAX_RESPONSE+1)),'JSON'),
    (aiohttp.ClientConnectionError(KEY),'无法连接'),(asyncio.TimeoutError(KEY),'超时')])
def test_catalogue_failures_safe_no_static_fallback(backend,monkeypatch,item,hint):
    transport(monkeypatch,[item])
    ref = EPHEMERAL_SECRET_STORE.put('dashscope',KEY)
    response = asyncio.run(catalog.api_models_route(request(reference=ref)))
    assert response.status==502 and hint in json.loads(response.text)['error']
    assert KEY not in response.text and ref not in response.text
    assert 'models' not in json.loads(response.text)


def test_hostile_model_id_cannot_echo_key_or_reference(backend,monkeypatch):
    ref = EPHEMERAL_SECRET_STORE.put('dashscope',KEY)
    transport(monkeypatch,[(200,{'data':[{'id':KEY},{'id':'echo-'+KEY[-8:]},{'id':ref},{'id':'qwen3-vl-plus'}]})])
    data = json.loads(asyncio.run(catalog.api_models_route(request(reference=ref))).text)
    assert data['models']==[{'id':'qwen3-vl-plus','vision':None}]


def test_runninghub_uses_application_catalogue_without_claiming_account_access(backend,monkeypatch):
    async def refresh(provider):
        assert provider=='runninghub'
        return ['openai/gpt-4.1']
    monkeypatch.setattr(backend,'_refresh_runninghub_models',refresh)
    ref = EPHEMERAL_SECRET_STORE.put('runninghub',KEY)
    data = json.loads(asyncio.run(catalog.api_models_route(request('runninghub',ref))).text)
    assert data['source']=='application' and data['models'][0]['id']=='openai/gpt-4.1'
