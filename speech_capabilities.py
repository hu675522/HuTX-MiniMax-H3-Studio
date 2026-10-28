"""Audit facts for the new speech UI; never changes existing video routing."""

def video_capabilities():
    rows = []
    for backend in ('local', 'fal'):
        for mode in ('i2v', 'fl2v', 'ref2va'):
            local = backend == 'local'
            rows.append(dict(backend=backend, mode=mode,
                model_family=('H3-Base-Ref2VA' if mode == 'ref2va' else 'H3-Base-FL2VA') if local else 'H3 Max',
                audio_input=('reference slots; video soundtracks precede audio' if mode == 'ref2va' else 'hybrid_audio') if local else ('reference_audio_urls' if mode == 'ref2va' else None),
                lock_source_in_code=local, verified_lip_sync=False,
                code_min_seconds=2 if local else 5, code_max_seconds=30 if local else 15,
                documented_max_seconds=15, fps=24 if local else None,
                frame_rule='17n+5, rounded upward' if local else 'provider managed',
                speech_bridge_enabled=local,
                reason='连接 Local driver_audio 并确认模型家族；安全帧预算最多 14.375 秒，口型效果需按具体 checkpoint 验收。' if local else
                    ('仅支持音频参考，当前 API 无原音频锁定字段。' if mode == 'ref2va' else '当前路由没有音频输入字段。')))
    for mode in ('i2v', 'fl2v', 'ref2va'):
        row = next(r for r in rows if r['backend'] == 'fal' and r['mode'] == mode).copy()
        row['model_family'] = 'H3 Max Turbo'
        if mode == 'ref2va':
            row['audio_input'] = None
            row['reason'] = '当前模型注册表没有 Turbo Reference-to-Video endpoint。'
        rows.append(row)
    return rows
