"""Fixed AUDIO inputs projected into existing Local reference slots."""
import copy


def bridge_references(state, task, audios, requested, calculate_length):
    from .speech_nodes import tensor_reference
    from .speech_bridge import store_audio
    import torch
    connected = [(i, audio) for i, audio in enumerate(audios, 1) if audio is not None]
    if not connected:
        return state, None
    if task != 'ref2va':
        raise ValueError('三路角色音频仅用于全能参考；文本/首尾帧请使用原 driver_audio。')
    active = copy.deepcopy(state)
    entries = dict(active['media'])
    if not any(s.startswith(('ref_image_', 'ref_video_')) for s in entries):
        raise ValueError('全能参考请先添加图片或视频。')
    frames = calculate_length(requested)
    # Explicit role voices are the audio references for this execution.  A
    # reference video's embedded soundtrack must not silently become Audio 1
    # and shift A/B/C to Audio 2/3/4.  This is execution-only: disconnecting
    # the role inputs restores the saved video-soundtrack behavior.
    muted_video_slots = []
    for slot, entry in entries.items():
        if slot.startswith('ref_video_') and not entry.get('muted', False):
            entry['muted'] = True
            muted_video_slots.append(slot)
    pcms = []
    for index, audio in connected:
        slot = f'ref_audio_{index}'
        if slot in entries:
            raise ValueError(f'{slot} 已有上传音频，请移除该槽素材或断开角色接线，不会自动覆盖。')
        wave = audio.get('waveform') if isinstance(audio, dict) else None
        if not isinstance(wave, torch.Tensor) or not torch.isfinite(wave).all() or torch.any(wave.abs() > 1):
            raise ValueError('角色 AUDIO 波形无效，不会自动限幅。')
        pcm = tensor_reference(audio)
        if len(pcm.data) // (2 * pcm.channels) * 24 > frames * pcm.sample_rate:
            raise ValueError(f'角色 {"ABC"[index-1]} 音频超过当前视频时长，请调整台词或时长；不会截断。')
        pcms.append((slot, pcm))
    # Reference voices keep their real duration.  They are not drive tracks
    # and must not be padded to the target video duration before budgeting.
    if sum(pcm.seconds for _, pcm in pcms) > 15 + 1e-6:
        raise ValueError('独立参考音频真实时长累计超过 15 秒；请缩短台词或减少音频数量，不会拼接或截断。')
    if len(entries) + len(pcms) > 12:
        raise ValueError('参考素材累计超过 12 个。')
    for slot, pcm in pcms:
        entries[slot] = {'name': store_audio(pcm, 'roles'), 'kind': 'audio'}
    active['media'] = sorted(entries.items())
    return active, {'slots': [s for s, _ in pcms], 'audio_mode': 'reference_only',
                    'durations_seconds': [pcm.seconds for _, pcm in pcms],
                    'muted_reference_video_audio_slots': muted_video_slots}
