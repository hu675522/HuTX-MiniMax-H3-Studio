import asyncio
import json
import types
from pathlib import Path

import pytest

from hutx_minimax_h3_testpkg import workbench_media as media


def descriptor(filename='clip.mp4', **extra):
    return {'filename': filename, 'subfolder': 'video', 'type': 'output', **extra}


def history(file=None, node='GHLocalVideoInputDualEngineGH'):
    file = file or descriptor()
    return {'job': {'prompt': [0, 'job', {'2': {'class_type': node}}],
                    'outputs': {'20': {'videos': [file, file]}}}}


@pytest.fixture
def local(tmp_path, monkeypatch):
    output = tmp_path / 'output'
    (output / 'video').mkdir(parents=True)
    (output / 'video/clip.mp4').write_bytes(b'video')
    (output / 'video/keep.mp4').write_bytes(b'keep')
    (output / 'video/clip.json').write_text('metadata')
    monkeypatch.setattr(media.assembly, 'JOBS', {})
    return output, {'output': output, 'temp': tmp_path / 'temp'}


def test_delete_one_history_video_filters_refresh_without_changing_other_outputs(local):
    output, roots = local
    data = history()
    assert len(media.available_media(data, roots)) == 1
    assert media.delete_media({**descriptor(), 'prompt_id': 'job'}, data, roots) == descriptor()
    assert not (output / 'video/clip.mp4').exists()
    assert media.available_media(data, roots) == []
    assert (output / 'video/keep.mp4').read_bytes() == b'keep'
    assert (output / 'video/clip.json').read_text() == 'metadata'
    assert len(data['job']['outputs']['20']['videos']) == 2


@pytest.mark.parametrize('node', ['OtherVideoNode', 'SaveVideo'])
def test_rejects_non_hutx_history(local, node):
    output, roots = local
    assert not media.available_media(history(node=node), roots)
    with pytest.raises(media.AssemblyError, match='HuTX'):
        media.delete_media({**descriptor(), 'prompt_id': 'job'}, history(node=node), roots)
    assert (output / 'video/clip.mp4').exists()


@pytest.mark.parametrize('patch', [
    {'filename': '../keep.mp4'}, {'subfolder': '../output/video'},
    {'filename': 'C:\\outside.mp4'}, {'filename': '/outside.mp4'},
    {'filename': 'clip.json'}, {'type': 'input'}, {'type': []},
    {'subfolder': 'video/../video'}, {'filename': 'clip.mp4:stream'},
])
def test_rejects_invalid_or_escaping_history_paths(local, patch):
    output, roots = local
    file = descriptor(**patch)
    with pytest.raises(media.AssemblyError):
        media.delete_media({**file, 'prompt_id': 'job'}, history(file), roots)
    assert (output / 'video/clip.mp4').exists()


def test_rejects_forged_or_untracked_file(local):
    output, roots = local
    with pytest.raises(media.AssemblyError, match='HuTX'):
        media.delete_media({**descriptor('keep.mp4'), 'prompt_id': 'job'}, history(), roots)
    with pytest.raises(media.AssemblyError, match='HuTX'):
        media.delete_media({**descriptor(), 'prompt_id': 'other'}, history(), roots)
    assert (output / 'video/clip.mp4').exists()


def test_busy_assembly_protects_files(local, monkeypatch):
    output, roots = local
    monkeypatch.setattr(media.assembly, 'JOBS', {'busy': {'state': 'running'}})
    with pytest.raises(media.AssemblyError, match='拼接'):
        media.delete_media({**descriptor(), 'prompt_id': 'job'}, history(), roots)
    assert (output / 'video/clip.mp4').exists()


def test_windows_file_lock_reports_failure_without_removing_card_data(local, monkeypatch):
    output, roots = local
    def deny(*args, **kwargs):
        raise PermissionError('internal host path must not be exposed')
    monkeypatch.setattr(Path, 'unlink', deny)
    with pytest.raises(media.AssemblyError, match='被占用'):
        media.delete_media({**descriptor(), 'prompt_id': 'job'}, history(), roots)
    assert len(media.available_media(history(), roots)) == 1


def test_rejects_link_to_outside_output(local, tmp_path):
    _, roots = local
    outside = tmp_path / 'outside.mp4'
    outside.write_bytes(b'keep')
    linked = roots['output'] / 'video/link.mp4'
    try:
        linked.symlink_to(outside)
    except OSError:
        pytest.skip('Symlink creation is not available on this Windows host')
    with pytest.raises(media.AssemblyError):
        media.delete_media({**descriptor('link.mp4'), 'prompt_id': 'job'}, history(descriptor('link.mp4')), roots)
    assert outside.read_bytes() == b'keep'


def test_routes_bound_request_validate_origin_and_remove_only_selected_file(local, monkeypatch):
    output, roots = local
    queue = types.SimpleNamespace(get_history=lambda **_: history())
    monkeypatch.setattr(media, '_context', lambda: (queue, roots))
    class Request:
        host = '127.0.0.1:8188'
        content_type = 'application/json'
        def __init__(self, raw=None, origin='http://127.0.0.1:8188'):
            self.headers = {'Origin': origin}
            async def read(_):
                return raw if raw is not None else json.dumps({**descriptor(), 'prompt_id': 'job'}).encode()
            self.content = types.SimpleNamespace(read=read)
    async def check():
        response = await media.video_history(Request())
        assert len(json.loads(response.text)['videos']) == 1
        assert (await media.video_delete(Request(origin='https://foreign.invalid'))).status == 400
        assert (await media.video_delete(Request(raw=b'x' * 8193))).status == 400
        assert (await media.video_delete(Request(raw=b'not-json'))).status == 400
        assert (output / 'video/clip.mp4').exists()
        response = await media.video_delete(Request())
        assert response.status == 200
        assert json.loads(response.text)['deleted'] == descriptor()
        assert json.loads((await media.video_history(Request())).text)['videos'] == []
    asyncio.run(check())


def test_media_routes_registered_once_with_existing_assembly_routes(monkeypatch):
    import sys
    from aiohttp import web
    instance = types.SimpleNamespace(routes=web.RouteTableDef())
    monkeypatch.setitem(sys.modules, 'server', types.SimpleNamespace(PromptServer=types.SimpleNamespace(instance=instance)))
    media.assembly.register_workbench_routes()
    media.assembly.register_workbench_routes()
    paths = [(route.method, route.path) for route in instance.routes]
    assert paths.count(('GET', media.assembly.PREFIX + '/videos')) == 1
    assert paths.count(('POST', media.assembly.PREFIX + '/videos/delete')) == 1
    assert paths.count(('POST', media.assembly.PREFIX + '/assemble')) == 1
