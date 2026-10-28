"""Read provider model catalogues without sending prompts, media or raw keys to UI."""
from __future__ import annotations

import asyncio
import json
import re

import aiohttp
from aiohttp import web

from .credentials import resolve_prompt_optimizer_api_key
from .provider_errors import ProviderRequestError, provider_http_error, provider_transport_error
from .secrets import OptimizerCredentialError, redact_secret_text

ENDPOINTS = {
    'dashscope':'https://dashscope.aliyuncs.com/compatible-mode/v1/models',
    'openai':'https://api.openai.com/v1/models',
    'openrouter':'https://openrouter.ai/api/v1/models',
    'siliconflow':'https://api.siliconflow.cn/v1/models?sub_type=chat',
    'gemini':'https://generativelanguage.googleapis.com/v1beta/models',
}
MAX_MODELS=1000
MAX_RESPONSE=2*1024*1024
_NON_CHAT=re.compile(r'embed|rerank|whisper|(^|[/_-])tts([/_-]|$)|dall-e|gpt-image|(^|/)flux|stable-diffusion|(^|/)wanx|cosyvoice',re.I)


def normalize_models(data,provider):
    rows=data.get('models' if provider=='gemini' else 'data',[]) if isinstance(data,dict) else []
    if not isinstance(rows,list):raise ValueError('invalid catalogue')
    result={}
    for row in rows[:10000]:
        if not isinstance(row,dict):continue
        name=row.get('name' if provider=='gemini' else 'id')
        if not isinstance(name,str):continue
        if provider=='gemini':
            methods=row.get('supportedGenerationMethods')
            if not isinstance(methods,list) or 'generateContent' not in methods:continue
            name=name.removeprefix('models/')
        if not name or len(name)>240 or re.search(r'[\s\x00-\x1f\x7f]',name) or _NON_CHAT.search(name):continue
        architecture=row.get('architecture') if isinstance(row.get('architecture'),dict) else {}
        inputs,outputs=architecture.get('input_modalities'),architecture.get('output_modalities')
        if isinstance(outputs,list) and outputs and 'text' not in outputs:continue
        vision=('image' in inputs or 'video' in inputs) if isinstance(inputs,list) and inputs else None
        result[name]={'id':name,'vision':vision}
        if len(result)>=MAX_MODELS:break
    return sorted(result.values(),key=lambda row:row['id'].lower())


async def fetch_api_models(provider,key):
    if provider not in ENDPOINTS:raise ValueError('unsupported catalogue')
    headers={'x-goog-api-key':key} if provider=='gemini' else {'Authorization':'Bearer '+key}
    found={};token='';seen=set()
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        for _ in range(5):
            params={'pageSize':200,**({'pageToken':token} if token else {})} if provider=='gemini' else None
            async with session.get(ENDPOINTS[provider],headers=headers,params=params,allow_redirects=False) as response:
                raw=bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    raw.extend(chunk)
                    if len(raw)>MAX_RESPONSE:raise ProviderRequestError('response')
                text=raw.decode('utf-8',errors='replace')
                if response.status!=200:raise provider_http_error(response.status,text)
                data=json.loads(text)
            for row in normalize_models(data,provider):found[row['id']]=row
            if len(found)>=MAX_MODELS or provider!='gemini':break
            token=data.get('nextPageToken')
            if not isinstance(token,str) or not token or len(token)>2000 or token in seen:break
            seen.add(token)
    models=sorted(found.values(),key=lambda row:row['id'].lower())[:MAX_MODELS]
    if not models:raise ProviderRequestError('response')
    return models


async def api_models_route(request):
    key='';reference=request.headers.get('X-HuTX-Optimizer-Reference','')
    try:
        if set(request.query)-{'provider'}:raise OptimizerCredentialError('模型列表参数无效。')
        provider=request.query.get('provider','')
        if provider not in {*ENDPOINTS,'runninghub','runninghub_overseas'}:
            return web.json_response({'error':'当前平台未提供自动模型列表，请手动填写模型。','unsupported':True},status=400,headers={'Cache-Control':'no-store'})
        key=resolve_prompt_optimizer_api_key(provider,reference)
        if not key:raise OptimizerCredentialError('请先配置当前平台的 API Key，再获取模型列表。')
        if provider in {'runninghub','runninghub_overseas'}:
            from .legacy import _refresh_runninghub_models
            ids=await asyncio.wait_for(_refresh_runninghub_models(provider),timeout=16)
            models=normalize_models({'data':[{'id':name} for name in ids]},provider)
            source='application'
        else:
            models=await asyncio.wait_for(fetch_api_models(provider,key),timeout=18)
            source='api'
        # A hostile catalogue could echo credential fragments in model names.
        secrets=[value for value in (key,reference) if value]
        fragments=[part for value in secrets for part in (value,value[:8],value[-8:]) if len(part)>=8]
        models=[row for row in models if not any(part in row['id'] for part in fragments)]
        if not models:raise ProviderRequestError('response')
        return web.json_response({'provider':provider,'source':source,'models':models},headers={'Cache-Control':'no-store'})
    except OptimizerCredentialError as error:
        message=redact_secret_text(error,(key,reference));status=400
    except ProviderRequestError as error:
        message=redact_secret_text(error,(key,reference));status=502
    except (aiohttp.ClientError,asyncio.TimeoutError,ValueError) as error:
        message=str(provider_transport_error(error));status=502
    except Exception:
        message='无法获取模型列表，请检查当前平台凭证或稍后刷新。';status=502
    return web.json_response({'error':message},status=status,headers={'Cache-Control':'no-store'})
