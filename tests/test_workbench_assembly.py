"""Real small-video assembly checks; no model or provider is loaded."""
import subprocess
import threading
import asyncio
import json
import types
from pathlib import Path

import av
import numpy as np
import pytest
from hutx_minimax_h3_testpkg import workbench_assembly as assembly


def make_clip(path, color='red', frequency=440, size='128x96'):
    command = [assembly.ffmpeg_executable(), '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi',
               '-i', f'color=c={color}:s={size}:r=24:d=0.5']
    if frequency:
        command += ['-f', 'lavfi', '-i', f'sine=frequency={frequency}:sample_rate=48000:duration=0.5']
    command += ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-threads', '2']
    if frequency:
        command += ['-c:a', 'aac', '-ac', '2']
    subprocess.run([*command, str(path)], check=True, capture_output=True)


def descriptor(name):
    return {'filename': name, 'subfolder': '', 'type': 'output'}


def test_rejects_paths_outside_media_roots(tmp_path):
    for filename in ('../outside.mp4', 'C:\\outside.mp4', 'https://outside/video.mp4', '/outside.mp4'):
        with pytest.raises(assembly.AssemblyError):
            assembly.resolve_clip(descriptor(filename), {'output': tmp_path})
    other = tmp_path / 'source.mp4'
    other.write_bytes(b'not a video')
    with pytest.raises(assembly.AssemblyError):
        assembly.resolve_clip({**descriptor('source.mp4'), 'type': 'input'}, {'output': tmp_path})


def test_real_assembly_preserves_each_audio_and_silent_middle(tmp_path):
    paths = [tmp_path / name for name in ('one.mp4', 'silent.mp4', 'three.mp4')]
    make_clip(paths[0]);make_clip(paths[1], 'green', None);make_clip(paths[2], 'blue', 880)
    originals = [path.read_bytes() for path in paths]
    progress = []
    result = assembly.assemble_clips([descriptor(path.name) for path in paths], {'output': tmp_path}, tmp_path,
                                     progress=lambda done, total: progress.append((done,total)))
    final = tmp_path / result['subfolder'] / result['filename']
    with av.open(str(final)) as container:
        stream = container.streams.video[0]
        assert (stream.width, stream.height, float(stream.average_rate)) == (128,96,24)
        frames = list(container.decode(stream))
        assert 35 <= len(frames) <= 38
        assert frames[2].to_ndarray(format='rgb24')[...,0].mean() > 200
        assert frames[-3].to_ndarray(format='rgb24')[...,2].mean() > 200
    with av.open(str(final)) as container:
        audio = container.streams.audio[0]
        assert audio.rate == 48000
        samples = np.concatenate([frame.to_ndarray().mean(axis=0) for frame in container.decode(audio)])
    def span(start,end):
        return samples[int(start*48000):int(end*48000)]
    def peak(values):
        return np.fft.rfftfreq(len(values), 1/48000)[np.argmax(abs(np.fft.rfft(values)))]
    assert abs(peak(span(.12,.38))-440) < 15
    assert np.sqrt(np.mean(span(.68,.88)**2)) < .005
    assert abs(peak(span(1.15,1.38))-880) < 15
    assert [path.read_bytes() for path in paths] == originals
    assert progress[-1] == (4,4)
    assert not list(final.parent.glob('.assembly-*'))


def test_mismatched_sizes_reject_before_encoding(tmp_path, monkeypatch):
    for name in ('one.mp4','two.mp4'):(tmp_path/name).touch()
    def probe(path):return {'width':128 if path.name=='one.mp4' else 160,'height':96,'seconds':1,'audio':False}
    monkeypatch.setattr(assembly,'probe_clip',probe)
    monkeypatch.setattr(assembly,'ffmpeg_executable',lambda:pytest.fail('must reject before ffmpeg'))
    with pytest.raises(assembly.AssemblyError,match='分辨率不一致'):
        assembly.assemble_clips([descriptor('one.mp4'),descriptor('two.mp4')],{'output':tmp_path},tmp_path)


def test_cancel_removes_scratch_and_never_changes_sources(tmp_path, monkeypatch):
    for name in ('one.mp4','two.mp4'):(tmp_path/name).write_bytes(b'original')
    monkeypatch.setattr(assembly,'probe_clip',lambda _: {'width':128,'height':96,'seconds':1,'audio':False})
    cancel = threading.Event();cancel.set()
    with pytest.raises(assembly.AssemblyError,match='已取消'):
        assembly.assemble_clips([descriptor('one.mp4'),descriptor('two.mp4')],{'output':tmp_path},tmp_path,cancel)
    assert (tmp_path/'one.mp4').read_bytes() == b'original'
    assert not list((tmp_path/'video/HuTX_Workbench').iterdir())


def test_job_routes_restrict_origin_owner_and_report_result(tmp_path, monkeypatch):
    (tmp_path/'one.mp4').touch();(tmp_path/'two.mp4').touch()
    import sys
    folder=types.ModuleType('folder_paths')
    folder.get_output_directory=lambda:str(tmp_path)
    folder.get_temp_directory=lambda:str(tmp_path)
    monkeypatch.setitem(sys.modules,'folder_paths',folder)
    monkeypatch.setattr(assembly,'JOBS',{})
    monkeypatch.setattr(assembly,'_owner',lambda request:request.owner)
    monkeypatch.setattr(assembly,'assemble_clips',lambda *args:{'filename':'done.mp4','subfolder':'video','type':'output'})
    class Request:
        host='127.0.0.1:8190';content_type='application/json'
        def __init__(self,owner='one',origin='http://127.0.0.1:8190',job_id=''):
            self.owner=owner;self.headers={'Origin':origin};self.match_info={'job_id':job_id}
            async def read(_):return json.dumps({'clips':[descriptor('one.mp4'),descriptor('two.mp4')]}).encode()
            self.content=types.SimpleNamespace(read=read)
    async def check():
        denied=await assembly.assembly_start(Request(origin='https://foreign.invalid'))
        assert denied.status==400
        response=await assembly.assembly_start(Request())
        assert response.status==200
        job_id=json.loads(response.text)['job_id']
        assert (await assembly.assembly_status(Request(owner='two',job_id=job_id))).status==404
        assert (await assembly.assembly_cancel(Request(owner='two',job_id=job_id))).status==404
        await assembly.JOBS[job_id]['task']
        public=json.loads((await assembly.assembly_status(Request(job_id=job_id))).text)
        assert public['state']=='complete'
        assert public['result']['filename']=='done.mp4'
        assert 'owner' not in public and 'task' not in public
    asyncio.run(check())


@pytest.mark.parametrize('edit', [[], False, {'trim_start': -1}, {'trim_start': True}, {'trim_end': '2'},
    {'trim_start': 1, 'trim_end': 1.01}, {'volume': float('nan')}, {'volume': float('inf')},
    {'volume': 2.1}, {'muted': 1}, {'unexpected': 0}, {'trim_start': 10**400}])
def test_rejects_invalid_edits(edit):
    with pytest.raises(assembly.AssemblyError):
        assembly.clip_edit(edit)


def audio_samples(path):
    with av.open(str(path)) as container:
        return np.concatenate([frame.to_ndarray().mean(axis=0) for frame in container.decode(audio=0)])


def result_path(root, result):
    return root / result['subfolder'] / result['filename']


def test_real_single_trim_selects_correct_picture_and_audio(tmp_path):
    for name, color, frequency in [('red.mp4','red',440),('green.mp4','green',660),('blue.mp4','blue',880)]:
        make_clip(tmp_path/name,color,frequency)
    source = assembly.assemble_clips([descriptor(name) for name in ('red.mp4','green.mp4','blue.mp4')],{'output':tmp_path},tmp_path)
    source_bytes=result_path(tmp_path,source).read_bytes()
    clean={key:source[key] for key in ('filename','subfolder','type')}
    result=assembly.assemble_clips([{**clean,'edit':{'trim_start':.625,'trim_end':.875}}],{'output':tmp_path},tmp_path)
    final=result_path(tmp_path,result)
    with av.open(str(final)) as container:
        frames=list(container.decode(video=0))
        assert len(frames)==6
        rgb=frames[2].to_ndarray(format='rgb24')
        assert rgb[...,1].mean()>100 and rgb[...,0].mean()<30 and rgb[...,2].mean()<30
    samples=audio_samples(final)[int(.06*48000):int(.2*48000)]
    peak=np.fft.rfftfreq(len(samples),1/48000)[np.argmax(abs(np.fft.rfft(samples)))]
    assert abs(peak-660)<15
    assert result['edited_seconds']==.25
    assert result_path(tmp_path,source).read_bytes()==source_bytes


def test_real_gain_and_muting_do_not_leak_adjacent_audio(tmp_path):
    make_clip(tmp_path/'one.mp4')
    make_clip(tmp_path/'two.mp4','blue',880)
    baseline=assembly.assemble_clips([descriptor('two.mp4')],{'output':tmp_path},tmp_path)
    edited=assembly.assemble_clips([{**descriptor('one.mp4'),'edit':{'trim_start':.125,'trim_end':.375,'muted':True}},
                                  {**descriptor('two.mp4'),'edit':{'trim_start':.125,'trim_end':.375,'volume':.25}}],{'output':tmp_path},tmp_path)
    samples=audio_samples(result_path(tmp_path,edited))
    silence=samples[int(.06*48000):int(.2*48000)]
    quiet=samples[int(.32*48000):int(.44*48000)]
    loud=audio_samples(result_path(tmp_path,baseline))[int(.1*48000):int(.22*48000)]
    rms=lambda values:np.sqrt(np.mean(values**2))
    assert rms(silence)<.001
    assert .20 < rms(quiet)/rms(loud) < .30
    assert edited['edited_seconds']==.5
    assert not list((tmp_path/'video/HuTX_Workbench').glob('.assembly-*'))


def test_out_of_bounds_edit_rejects_before_encoding(tmp_path,monkeypatch):
    (tmp_path/'one.mp4').touch()
    monkeypatch.setattr(assembly,'probe_clip',lambda _: {'width':128,'height':96,'seconds':1,'audio':True})
    monkeypatch.setattr(assembly,'ffmpeg_executable',lambda:pytest.fail('must reject before encoding'))
    for edit in ({'trim_start':1},{'trim_end':2}):
        with pytest.raises(assembly.AssemblyError,match='超出'):
            assembly.assemble_clips([{**descriptor('one.mp4'),'edit':edit}],{'output':tmp_path},tmp_path)


def test_trim_beyond_short_audio_track_pads_silence(tmp_path):
    source=tmp_path/'short-audio.mp4'
    subprocess.run([assembly.ffmpeg_executable(),'-nostdin','-hide_banner','-loglevel','error','-y',
        '-f','lavfi','-i','color=c=red:s=128x96:r=24:d=0.5',
        '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=0.1',
        '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-ac','2','-threads','2',str(source)],check=True,capture_output=True)
    result=assembly.assemble_clips([{**descriptor(source.name),'edit':{'trim_start':.25,'trim_end':.5}}],{'output':tmp_path},tmp_path)
    samples=audio_samples(result_path(tmp_path,result))
    assert len(samples)>=12000 and np.max(abs(samples))<.001
