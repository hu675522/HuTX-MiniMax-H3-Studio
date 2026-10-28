"""Local workbench video inventory and bounded deletion; no inference changes."""
from __future__ import annotations

import json

from . import workbench_assembly as assembly
from .workbench_assembly import AssemblyError, _check_origin, resolve_clip

VIDEO_NODES = {'GHLocalVideoInputDualEngineGH', 'GHLocalVideoInputGH'}


def media_identity(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get('filename'), str):
        raise AssemblyError('视频文件信息无效。')
    identity = {key: raw.get(key, default) for key, default in
                (('filename', ''), ('subfolder', ''), ('type', 'output'))}
    if not all(isinstance(value, str) for value in identity.values()) or identity['type'] not in ('output', 'temp'):
        raise AssemblyError('视频文件信息无效。')
    return identity


def history_media(history):
    """Only outputs belonging to HuTX video executions, never arbitrary paths."""
    for prompt_id, record in reversed(list(history.items())):
        prompt = record.get('prompt', [])
        graph = prompt[2] if len(prompt) > 2 else None
        if not isinstance(graph, dict) or not any(
                isinstance(node, dict) and node.get('class_type') in VIDEO_NODES for node in graph.values()):
            continue
        for node_id, output in record.get('outputs', {}).items():
            for field in ('videos', 'gifs', 'images'):
                items = output.get(field, [])
                for raw in items if isinstance(items, list) else []:
                    try:
                        identity = media_identity(raw)
                    except AssemblyError:
                        continue
                    yield {**identity, 'promptId': prompt_id, 'nodeId': node_id, 'title': identity['filename']}


def media_path(file, roots):
    identity = media_identity(file)
    resolved = resolve_clip(identity, roots)
    # Do not follow a history entry that aliases a different file through a link.
    from pathlib import Path
    candidate = Path(roots[identity['type']]).resolve() / identity['subfolder'] / identity['filename']
    if candidate.absolute() != resolved or candidate.is_symlink():
        raise AssemblyError('无法删除或管理链接形式的视频，请使用原始输出文件。')
    return resolved


def available_media(history, roots):
    videos, seen = [], set()
    for file in history_media(history):
        try:
            path = media_path(file, roots)
        except (AssemblyError, OSError, ValueError):
            continue
        if path in seen:
            continue
        seen.add(path)
        videos.append(file)
        if len(videos) >= 100:
            break
    return videos


def delete_media(raw, history, roots):
    if not isinstance(raw, dict) or set(raw) != {'filename', 'subfolder', 'type', 'prompt_id'}:
        raise AssemblyError('删除参数无效。')
    if not isinstance(raw['prompt_id'], str) or not 0 < len(raw['prompt_id']) <= 128:
        raise AssemblyError('生成记录无效，请刷新列表。')
    identity = media_identity(raw)
    if not any(media_identity(file) == identity and file['promptId'] == raw['prompt_id']
               for file in history_media(history)):
        raise AssemblyError('未找到对应的 HuTX 生成记录，请刷新列表。')
    if any(job['state'] == 'running' for job in assembly.JOBS.values()):
        raise AssemblyError('拼接正在使用视频，请等待或取消拼接后再删除。')
    path = media_path(identity, roots)
    try:
        path.unlink()
    except PermissionError:
        raise AssemblyError('视频正在被占用，请停止预览后重试。') from None
    except OSError:
        raise AssemblyError('删除失败，请检查视频文件是否存在及目录权限。') from None
    return identity


def _context():
    import folder_paths
    from server import PromptServer
    return PromptServer.instance.prompt_queue, {
        'output': folder_paths.get_output_directory(), 'temp': folder_paths.get_temp_directory()}


async def video_history(request):
    from aiohttp import web
    queue, roots = _context()
    return web.json_response({'videos': available_media(queue.get_history(max_items=50), roots)},
                             headers={'Cache-Control': 'no-store'})


async def video_delete(request):
    from aiohttp import web
    try:
        _check_origin(request)
        if request.content_type != 'application/json':
            raise AssemblyError('请使用 JSON 请求。')
        body = await request.content.read(8193)
        if len(body) > 8192:
            raise AssemblyError('删除请求过大。')
        raw = json.loads(body)
        if not isinstance(raw, dict) or not isinstance(raw.get('prompt_id'), str):
            raise AssemblyError('生成记录无效。')
        queue, roots = _context()
        deleted = delete_media(raw, queue.get_history(prompt_id=raw['prompt_id']), roots)
        return web.json_response({'deleted': deleted}, headers={'Cache-Control': 'no-store'})
    except (AssemblyError, ValueError, KeyError) as error:
        return web.json_response({'error': str(error) if isinstance(error, AssemblyError) else '删除请求无效。'}, status=400)
