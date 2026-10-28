"""Local UI metadata only. No model loading, media decoding or Fal transport."""
from pathlib import Path


def inspect_local_media(name, input_directory):
    from .local_video_state import local_state
    local_state({'media': [['first_frame', {'name': name}]]})
    root = Path(input_directory).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Local input media is unavailable.')
    try:
        from PIL import Image
        with Image.open(path) as image:
            return {'width': image.width, 'height': image.height, 'has_audio': False}
    except (OSError, ValueError):
        import av
        with av.open(str(path)) as container:
            video = next(iter(container.streams.video), None)
            return {'width': video.width if video else 0, 'height': video.height if video else 0,
                    'has_audio': bool(container.streams.audio)}


async def local_media_info(request):
    import asyncio
    import folder_paths
    from aiohttp import web
    try:
        result = await asyncio.to_thread(inspect_local_media, request.query.get('name', ''), folder_paths.get_input_directory())
        return web.json_response(result, headers={'Cache-Control': 'no-store'})
    except Exception:
        return web.json_response({'error': '无法读取本地素材信息；请重新选择有效素材。'}, status=400)


def register_local_media_routes():
    from server import PromptServer
    instance = PromptServer.instance
    if getattr(instance, '_hutx_local_media_routes', None) is instance.routes:
        return
    instance.routes.get('/hutx/minimax-h3/local-media-info')(local_media_info)
    instance._hutx_local_media_routes = instance.routes
