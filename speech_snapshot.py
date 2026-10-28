"""Explicit adopted audio snapshots survive cache expiry and video retries."""
import hashlib
import json
import re
import os
import tempfile
from pathlib import Path
from .speech_validation import SpeechError


def save_snapshot(result):
    from .speech_bridge import store_audio
    import folder_paths
    relative=store_audio(result.pcm,'adopted')
    # Bind each acceptance to its public parameter fingerprint without saving text.
    root=Path(folder_paths.get_input_directory()).resolve()
    meta={'schema':1,'fingerprint':result.input_fingerprint,'audio':relative,
          'report':result.public()['report']}
    blob=json.dumps(meta,ensure_ascii=False,sort_keys=True).encode()
    identifier=hashlib.sha256(blob).hexdigest()
    path=(root/'hutx-speech/adopted'/f'{identifier}.json').resolve()
    if not path.is_relative_to(root):raise SpeechError('采用音频存储目录无效。')
    handle,temporary=tempfile.mkstemp(prefix='.writing-',dir=path.parent)
    try:
        with os.fdopen(handle,'wb') as stream:stream.write(blob)
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    return path.relative_to(root).as_posix()


def _read_snapshot(relative):
    from .speech_service import decode_wav
    import folder_paths
    if not isinstance(relative,str) or not re.fullmatch(r'hutx-speech/adopted/[a-f0-9]{64}\.json',relative):
        raise SpeechError('采用音频路径无效，请重新采用。')
    root=Path(folder_paths.get_input_directory()).resolve();path=(root/relative).resolve()
    try:
        if not path.is_relative_to(root):raise ValueError()
        blob=path.read_bytes()
        if hashlib.sha256(blob).hexdigest()!=path.stem:raise ValueError()
        meta=json.loads(blob)
        if meta['schema']!=1:raise ValueError()
        audio=meta['audio']
        if not re.fullmatch(r'hutx-speech/adopted/[a-f0-9]{64}\.wav',audio):raise ValueError()
        file=(root/audio).resolve()
        if not file.is_relative_to(root):raise ValueError()
        data=file.read_bytes()
        if hashlib.sha256(data).hexdigest()!=file.stem:raise ValueError()
        return path,meta,decode_wav(data)
    except Exception:raise SpeechError('采用音频已缺失、损坏或参数已变化，请重新试听并采用；未自动重新调用 TTS。') from None


def snapshot_summary(relative):
    _,meta,pcm=_read_snapshot(relative)
    return {'audio_file':meta['audio'],'duration_seconds':pcm.seconds}


def load_snapshot(relative,expected):
    from .speech_service import Result
    path,meta,pcm=_read_snapshot(relative)
    try:
        if meta['fingerprint']!=expected:raise ValueError()
        report=meta['report']
        return Result(path.stem[:32],pcm,0,report['engine'],report['mode'],report['is_mock'],report['model_version'],expected)
    except Exception:
        raise SpeechError('采用音频已缺失、损坏或参数已变化，请重新试听并采用；未自动重新调用 TTS。') from None
