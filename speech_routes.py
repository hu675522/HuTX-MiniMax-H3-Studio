"""Local mock preview routes. No cloud transports and no credential inputs."""
import asyncio
import re
import threading
from .speech_service import SPEECH_SERVICE, catalog, read_reference
from .speech_validation import SpeechError, SpeechCancelled
from .speech_errors import SpeechFailure

JOBS = {}
PREFIX = '/hutx/minimax-h3/speech'


async def speech_catalog(request):
    from aiohttp import web
    return web.json_response(catalog(), headers={'Cache-Control': 'no-store'})


async def speech_generate(request):
    from aiohttp import web
    job_id = None
    cancel = None
    try:
        data = await request.json()
        if not isinstance(data, dict) or set(data) - {'request_id', 'parameters', 'reference_file'}:
            raise SpeechError('请求包含不支持的字段。')
        job_id = data.get('request_id', '')
        if not isinstance(job_id, str) or not re.fullmatch(r'[a-f0-9-]{32,36}', job_id):
            raise SpeechError('请求标识无效。')
        if job_id in JOBS or len(JOBS) >= 8:
            raise SpeechError('口播任务正在运行，请稍后重试。')
        cancel = threading.Event()
        JOBS[job_id] = cancel
        parameters = data.get('parameters')
        if isinstance(parameters,dict) and parameters.get('engine')=='local' and not parameters.get('mock_demo'):
            try:
                from server import PromptServer
                if PromptServer.instance.prompt_queue.get_tasks_remaining():
                    raise SpeechFailure('queue_busy')
            except ImportError:pass
        filename = data.get('reference_file', '')
        def generate():
            reference = read_reference(filename) if isinstance(parameters, dict) and parameters.get('mode') == 'clone' else None
            if isinstance(parameters,dict) and parameters.get('engine')=='local' and not parameters.get('mock_demo'):
                from .speech_queue import local_preview_gate
                with local_preview_gate():
                    return SPEECH_SERVICE.generate(parameters, reference, cancel)
            return SPEECH_SERVICE.generate(parameters, reference, cancel)
        result, cached = await asyncio.to_thread(generate)
        return web.json_response(result.public(cached), headers={'Cache-Control': 'no-store'})
    except SpeechCancelled:
        return web.json_response({'error': '已取消。', 'cancelled': True}, status=409)
    except SpeechFailure as exc:
        return web.json_response({'error':str(exc),'code':exc.code},status=400)
    except SpeechError as exc:
        return web.json_response({'error': str(exc)}, status=400)
    except Exception:
        return web.json_response({'error': '口播请求失败。'}, status=400)
    finally:
        if cancel is not None and JOBS.get(job_id) is cancel:
            JOBS.pop(job_id, None)


async def speech_cancel(request):
    from aiohttp import web
    try:
        data = await request.json()
        if not isinstance(data, dict) or set(data) != {'request_id'} or not isinstance(data['request_id'], str):
            raise ValueError()
        cancel = JOBS.get(data['request_id'])
        if cancel is not None:
            cancel.set()
        return web.json_response({'cancelled': cancel is not None})
    except Exception:
        return web.json_response({'error': '取消请求无效。'}, status=400)


async def speech_audio(request):
    from aiohttp import web
    try:
        data = SPEECH_SERVICE.audio(request.match_info['audio_id'])
        return web.Response(body=data, content_type='audio/wav', headers={'Cache-Control': 'no-store'})
    except SpeechError:
        return web.json_response({'error': '试听音频已失效，请重新生成。'}, status=404)


async def speech_adopt(request):
    from aiohttp import web
    try:
        data=await request.json()
        if not isinstance(data,dict) or set(data)!={'audio_id'} or not isinstance(data['audio_id'],str):raise ValueError()
        filename=await asyncio.to_thread(SPEECH_SERVICE.adopt,data['audio_id'])
        return web.json_response({'adopted_audio_file':filename},headers={'Cache-Control':'no-store'})
    except Exception:return web.json_response({'error':'音频采用失败，请重新生成并试听。'},status=400)


async def speech_credential(request):
    from aiohttp import web
    from .speech_credentials import SPEECH_CREDENTIALS
    data={}
    try:
        if request.method=='POST':
            data=await request.json()
            if not isinstance(data,dict) or set(data)!={'key','storage'}:raise SpeechError('凭证参数无效。')
            SPEECH_CREDENTIALS.save(data.pop('key'),data['storage'])
        elif request.method=='DELETE':SPEECH_CREDENTIALS.delete()
        return web.json_response(SPEECH_CREDENTIALS.status(),headers={'Cache-Control':'no-store'})
    except SpeechError as exc:return web.json_response({'error':str(exc)},status=400)
    except Exception:return web.json_response({'error':'语音凭证操作失败。'},status=400)
    finally:
        if isinstance(data,dict):data.clear()


async def speech_adopted_preview(request):
    from aiohttp import web
    from .speech_snapshot import snapshot_summary
    try:
        if set(request.query)!={'file'}:raise ValueError()
        data=await asyncio.to_thread(snapshot_summary,request.query['file'])
        return web.json_response(data,headers={'Cache-Control':'no-store'})
    except Exception:
        return web.json_response({'error':'已采用口播不可用，请重新试听并采用。'},status=400)


async def speech_voice(request):
    from aiohttp import web
    from .speech_local import local_voices,save_voice
    try:
        if request.method=='POST':
            data=await request.json()
            if not isinstance(data,dict) or set(data)!={'name','reference_text','reference_file'}:raise SpeechError('音色参数无效。')
            reference=read_reference(data['reference_file'])
            if reference is None:raise SpeechError('请先提供参考录音。')
            save_voice(data['name'],data['reference_text'],reference)
        return web.json_response({'voices':local_voices()},headers={'Cache-Control':'no-store'})
    except Exception:return web.json_response({'error':'保存本机音色失败，请检查录音、名称和原文。'},status=400)


def register_speech_routes():
    from server import PromptServer
    instance = PromptServer.instance
    from .speech_queue import install_queue_gate
    install_queue_gate(instance)
    if getattr(instance, '_hutx_speech_routes', None) is instance.routes:
        return
    instance.routes.get(PREFIX + '/catalog')(speech_catalog)
    instance.routes.post(PREFIX + '/generate')(speech_generate)
    instance.routes.post(PREFIX + '/cancel')(speech_cancel)
    instance.routes.get(PREFIX + '/audio/{audio_id}')(speech_audio)
    instance.routes.post(PREFIX + '/adopt')(speech_adopt)
    instance.routes.get(PREFIX + '/adopted-preview')(speech_adopted_preview)
    instance.routes.get(PREFIX + '/credential')(speech_credential)
    instance.routes.post(PREFIX + '/credential')(speech_credential)
    instance.routes.delete(PREFIX + '/credential')(speech_credential)
    instance.routes.get(PREFIX + '/voices')(speech_voice)
    instance.routes.post(PREFIX + '/voices')(speech_voice)
    instance._hutx_speech_routes = instance.routes
