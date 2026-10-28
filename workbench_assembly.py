"""Bounded local clip assembly. Uses existing PyAV and imageio-ffmpeg; no models."""
from __future__ import annotations

import asyncio
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit
import uuid

PREFIX = '/hutx/minimax-h3/workbench'
MAX_CLIPS = 32
MAX_SECONDS = 600
JOBS: dict[str, dict] = {}


class AssemblyError(ValueError):
    pass


def resolve_clip(raw, roots):
    if not isinstance(raw, dict) or set(raw) - {'filename', 'subfolder', 'type', 'title', 'edit'}:
        raise AssemblyError('片段文件信息无效。')
    clip_edit(raw.get('edit'))
    filename, subfolder, kind = raw.get('filename'), raw.get('subfolder', ''), raw.get('type', 'output')
    if kind not in ('output', 'temp') or kind not in roots:
        raise AssemblyError('只支持 ComfyUI 的本机输出或临时视频。')
    for value in (filename, subfolder):
        if not isinstance(value, str) or len(value) > 1024 or re.search(r'[\\:\x00-\x1f]', value) or value.startswith('/') or any(part in ('.', '..') for part in value.split('/')):
            raise AssemblyError('片段路径无效。')
    if Path(filename).suffix.lower() not in ('.mp4', '.webm', '.mov', '.mkv', '.m4v'):
        raise AssemblyError('片段不是支持的视频格式。')
    root = Path(roots[kind]).resolve()
    path = (root / subfolder / filename).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise AssemblyError('片段已移动或失效，请重新选择视频。')
    return path


def clip_edit(raw=None, seconds=None):
    defaults = {'trim_start': 0, 'trim_end': None, 'volume': 1, 'muted': False}
    if raw is not None and (not isinstance(raw, dict) or set(raw) - set(defaults)):
        raise AssemblyError('片段编辑参数无效。')
    edit = {**defaults, **(raw or {})}
    def number(value):
        return type(value) is int or (type(value) is float and math.isfinite(value))
    start, end, gain = edit['trim_start'], edit['trim_end'], edit['volume']
    if (not number(start) or not 0 <= start < 120 or
            (end is not None and (not number(end) or end > 120 or end - start < 1 / 24 - 1e-8)) or
            not number(gain) or not 0 <= gain <= 2 or not isinstance(edit['muted'], bool)):
        raise AssemblyError('裁剪需至少保留一帧，音量范围为 0–200%。')
    if seconds is not None:
        end = seconds if end is None else end
        if end > seconds + .001 or end - start < 1 / 24 - 1e-8:
            raise AssemblyError('裁剪范围超出原片段，请调整入点和出点。')
        edit['trim_end'] = min(end, seconds)
        edit['seconds'] = math.ceil((edit['trim_end'] - start) * 24 - 1e-7) / 24
    return edit


def probe_clip(path):
    import av
    try:
        with av.open(str(path), options={'protocol_whitelist': 'file,pipe'}) as container:
            stream = next(iter(container.streams.video), None)
            if stream is None:
                raise AssemblyError('片段没有视频画面。')
            seconds = float(stream.duration * stream.time_base) if stream.duration is not None else float(container.duration or 0) / av.time_base
            if not math.isfinite(seconds) or not 0 < seconds <= 120 or not 0 < stream.width <= 4096 or not 0 < stream.height <= 4096 or stream.width * stream.height > 4096 * 2160:
                raise AssemblyError('片段尺寸或时长超过当前拼接范围。')
            if stream.width % 2 or stream.height % 2:
                raise AssemblyError('片段宽高需为偶数，无法直接导出 H.264。')
            return {'width': stream.width, 'height': stream.height, 'seconds': seconds, 'audio': bool(container.streams.audio)}
    except AssemblyError:
        raise
    except Exception:
        raise AssemblyError('无法读取片段，请确认视频文件完整。') from None


def ffmpeg_executable():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(arguments, cancel, deadline):
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=errors, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            while process.poll() is None:
                if cancel.wait(.15):
                    raise AssemblyError('拼接已取消。')
                if time.monotonic() >= deadline:
                    raise AssemblyError('拼接超时，请减少片段或分辨率后重试。')
            if process.returncode:
                # Never return command lines, host paths or raw decoder output.
                raise AssemblyError('视频编码失败，请检查输入格式与磁盘空间。')
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


def assemble_clips(clips, roots, output_root, cancel=None, progress=None):
    cancel = cancel or threading.Event()
    progress = progress or (lambda *_: None)
    if not isinstance(clips, list) or not 1 <= len(clips) <= MAX_CLIPS:
        raise AssemblyError('请选择 1 至 32 个片段。')
    paths = [resolve_clip(item, roots) for item in clips]
    facts = [probe_clip(path) for path in paths]
    if len({(item['width'], item['height']) for item in facts}) != 1:
        raise AssemblyError('片段分辨率不一致，请先使用相同画布尺寸生成；本阶段不自动拉伸。')
    edits = [clip_edit(item.get('edit'), info['seconds']) for item, info in zip(clips, facts)]
    total = sum(item['seconds'] for item in edits)
    if total > MAX_SECONDS:
        raise AssemblyError('当前拼接累计时长最多 10 分钟。')
    output_root = Path(output_root).resolve()
    destination = output_root / 'video' / 'HuTX_Workbench'
    if not destination.resolve().is_relative_to(output_root):
        raise AssemblyError('输出目录无效。')
    destination.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    final = destination / f'assembled_{token}.mp4'
    exe = ffmpeg_executable()
    deadline = time.monotonic() + 1800
    try:
        # Own scratch tree, distinct from all source paths and previous jobs.
        with tempfile.TemporaryDirectory(prefix='.assembly-', dir=destination) as scratch:
            scratch = Path(scratch)
            for index, (source, info, edit) in enumerate(zip(paths, facts, edits)):
                if cancel.is_set():
                    raise AssemblyError('拼接已取消。')
                progress(index, len(paths) + 1)
                seconds = f"{edit['seconds']:.9f}"
                start, end = f"{edit['trim_start']:.9f}", f"{edit['trim_end']:.9f}"
                use_audio = info['audio'] and not edit['muted'] and edit['volume'] > 0
                command = [exe, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-protocol_whitelist', 'file,pipe', '-i', str(source)]
                if not use_audio:
                    command += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
                audio_filter = f'atrim=start={start}:end={end},' if use_audio else ''
                audio_filter += f'asetpts=PTS-STARTPTS,aresample=48000,volume={edit["volume"]:.6f},apad,atrim=duration={seconds}'
                command += ['-map', '0:v:0', '-map', '0:a:0' if use_audio else '1:a:0',
                            '-vf', f'trim=start={start}:end={end},setpts=PTS-STARTPTS,fps=24,tpad=stop_mode=clone:stop_duration=0.05,setsar=1,format=yuv420p',
                            '-af', audio_filter,
                            '-t', seconds, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18',
                            '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
                            '-map_metadata', '-1', '-threads', '2', str(scratch / f'{index:03d}.mp4')]
                run_ffmpeg(command, cancel, deadline)
            # Controlled relative names prevent concat-list injection and remote reads.
            listing = scratch / 'clips.txt'
            listing.write_text(''.join(f"file '{index:03d}.mp4'\n" for index in range(len(paths))), encoding='utf-8')
            joined = scratch / 'joined.mp4'
            progress(len(paths), len(paths) + 1)
            run_ffmpeg([exe, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '1',
                        '-i', str(listing), '-c', 'copy', '-movflags', '+faststart', '-map_metadata', '-1', str(joined)], cancel, deadline)
            if cancel.is_set():
                raise AssemblyError('拼接已取消。')
            import av
            with av.open(str(joined)) as container:
                if not container.streams.video or not container.streams.audio:
                    raise AssemblyError('拼接结果缺少画面或音轨。')
            os.replace(joined, final)
        progress(len(paths) + 1, len(paths) + 1)
        return {'filename': final.name, 'subfolder': 'video/HuTX_Workbench', 'type': 'output',
                'title': '拼接成片', 'clip_count': len(paths), 'source_seconds': round(sum(item['seconds'] for item in facts), 3), 'edited_seconds': round(total, 3),
                'width': facts[0]['width'], 'height': facts[0]['height'], 'fps': 24}
    except Exception:
        final.unlink(missing_ok=True)
        raise


def _owner(request):
    from server import PromptServer
    return PromptServer.instance.user_manager.get_request_user_id(request)


def _check_origin(request):
    origin = request.headers.get('Origin')
    if origin and urlsplit(origin).netloc.lower() != request.host.lower():
        raise AssemblyError('请从当前 ComfyUI 页面提交拼接。')


def _public(job):
    return {key: job[key] for key in ('job_id', 'state', 'completed', 'total', 'result', 'error')}


async def assembly_start(request):
    from aiohttp import web
    import folder_paths
    try:
        _check_origin(request)
        if request.content_type != 'application/json':
            raise AssemblyError('请使用 JSON 请求。')
        body = await request.content.read(65537)
        if len(body) > 65536:
            raise AssemblyError('拼接请求过大。')
        data = json.loads(body)
        if not isinstance(data, dict) or set(data) != {'clips'}:
            raise AssemblyError('拼接参数无效。')
        clips = data['clips']
        if not isinstance(clips, list) or not 1 <= len(clips) <= MAX_CLIPS:
            raise AssemblyError('请选择 1 至 32 个片段。')
        roots = {'output': folder_paths.get_output_directory(), 'temp': folder_paths.get_temp_directory()}
        for item in clips:
            resolve_clip(item, roots)
        owner = _owner(request)
        if any(job['state'] == 'running' for job in JOBS.values()):
            raise AssemblyError('已有拼接任务正在运行，请等待完成。')
        for key, job in list(JOBS.items()):
            if job['state'] != 'running' and (time.monotonic() - job['created'] > 3600 or len(JOBS) >= 10):
                JOBS.pop(key, None)
        job_id = uuid.uuid4().hex
        job = {'job_id': job_id, 'state': 'running', 'completed': 0, 'total': len(clips) + 1,
               'result': None, 'error': '', 'owner': owner, 'cancel': threading.Event(), 'created': time.monotonic()}
        JOBS[job_id] = job
        async def execute():
            def progress(done, total):
                job.update(completed=done, total=total)
            try:
                result = await asyncio.to_thread(assemble_clips, clips, roots, roots['output'], job['cancel'], progress)
                job.update(state='complete', result=result)
            except AssemblyError as error:
                job.update(state='cancelled' if job['cancel'].is_set() else 'error', error=str(error))
            except Exception:
                job.update(state='error', error='拼接失败，请检查本地视频工具与磁盘空间。')
        job['task'] = asyncio.create_task(execute())
        return web.json_response(_public(job), headers={'Cache-Control': 'no-store'})
    except (AssemblyError, ValueError, KeyError) as error:
        return web.json_response({'error': str(error) if isinstance(error, AssemblyError) else '拼接请求无效。'}, status=400)


async def assembly_status(request):
    from aiohttp import web
    try:
        job = JOBS.get(request.match_info['job_id'])
        if not job or job['owner'] != _owner(request):
            return web.json_response({'error': '拼接任务不存在或已过期。'}, status=404)
        return web.json_response(_public(job), headers={'Cache-Control': 'no-store'})
    except KeyError:
        return web.json_response({'error': '拼接任务不可用。'}, status=404)


async def assembly_cancel(request):
    from aiohttp import web
    try:
        _check_origin(request)
        job = JOBS.get(request.match_info['job_id'])
        if not job or job['owner'] != _owner(request):
            return web.json_response({'error': '拼接任务不存在。'}, status=404)
        if job['state'] == 'running':
            job['cancel'].set()
        return web.json_response(_public(job), headers={'Cache-Control': 'no-store'})
    except (AssemblyError, KeyError):
        return web.json_response({'error': '无法取消该拼接任务。'}, status=400)


def register_workbench_routes():
    from server import PromptServer
    instance = PromptServer.instance
    if getattr(instance, '_hutx_workbench_routes', None) is instance.routes:
        return
    from .workbench_media import video_history, video_delete
    instance.routes.get(PREFIX + '/videos')(video_history)
    instance.routes.post(PREFIX + '/videos/delete')(video_delete)
    instance.routes.post(PREFIX + '/assemble')(assembly_start)
    instance.routes.get(PREFIX + '/assemble/{job_id}')(assembly_status)
    instance.routes.post(PREFIX + '/assemble/{job_id}/cancel')(assembly_cancel)
    instance._hutx_workbench_routes = instance.routes
