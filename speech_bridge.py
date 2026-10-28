"""Opt-in Local AUDIO bridge. No Fal requests, no new media tag grammar."""
import copy
import hashlib
import math
import os
import tempfile
from pathlib import Path


def fit_duration(samples,rate,requested,calculate_length):
    if type(samples) is not int or samples<=0 or type(rate) is not int or rate<=0:
        raise ValueError('驱动音频为空或采样率无效。')
    if type(requested) is not int or not 2<=requested<=30:raise ValueError('视频时长必须为整数。')
    # Use integer arithmetic: never truncate speech to fit a nominal 15 seconds.
    for seconds in range(max(4,requested),16):
        frames=calculate_length(seconds)
        if frames<=360 and frames*rate>=samples*24:
            return seconds,frames
    raise ValueError(f'口播 {samples/rate:.3f}s 或所选视频时长超出当前帧预算。'
                     '当前整数秒接口最多 345 帧 / 14.375s；请精简台词、调整语速或明确选择片段，不会自动截断。')


def store_audio(pcm,subdirectory='driver'):
    from .speech_service import wav_bytes
    import folder_paths
    root=Path(folder_paths.get_input_directory()).resolve()
    directory=(root/'hutx-speech'/subdirectory).resolve()
    if not directory.is_relative_to(root):raise ValueError('音频存储目录越界。')
    directory.mkdir(parents=True,exist_ok=True)
    data=wav_bytes(pcm);digest=hashlib.sha256(data).hexdigest();target=directory/(digest+'.wav')
    if target.exists():
        if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError('已保存音频校验失败。')
    else:
        handle,name=tempfile.mkstemp(prefix='.writing-',dir=directory)
        try:
            with os.fdopen(handle,'wb') as stream:stream.write(data)
            os.replace(name,target)
        finally:
            if os.path.exists(name):os.unlink(name)
    return target.relative_to(root).as_posix()


def bridge_audio(state,task,audio,requested,family,policy,target,calculate_length,inspect=None):
    from .speech_nodes import tensor_reference
    import torch
    if family not in ('FL2VA','Ref2VA'):raise ValueError('接入口播前，请明确确认主模型家族为 FL2VA 或 Ref2VA。')
    if task not in ('i2va','l2va','fl2va','ref2va'):raise ValueError('口播桥接仅开放 I2V、L2V、FL2V、Ref2VA；请先连接首帧、尾帧或参考画面。')
    if family != ('Ref2VA' if task=='ref2va' else 'FL2VA'):raise ValueError('口播模式与已确认的模型家族不匹配。')
    if policy not in ('reject_conflicts','use_connected_audio'):raise ValueError('请选择有效的音频冲突处理方式。')
    waveform=audio.get('waveform') if isinstance(audio,dict) else None
    if not isinstance(waveform,torch.Tensor) or not torch.isfinite(waveform).all() or torch.any(waveform.abs()>1):
        raise ValueError('驱动 AUDIO 必须是有限且在 [-1,1] 范围内的波形，不会自动限幅。')
    pcm=tensor_reference(audio);samples=len(pcm.data)//(2*pcm.channels)
    seconds,frames=fit_duration(samples,pcm.sample_rate,requested,calculate_length)
    active=copy.deepcopy(state);entries=dict(active['media']);soundtracks=0
    replaced=None
    if task=='ref2va':
        if not any(slot.startswith(('ref_image_','ref_video_')) for slot in entries):raise ValueError('Ref2VA 口播必须有图片或视频参考。')
        audios=sorted(slot for slot in entries if slot.startswith('ref_audio_'))
        if inspect is None:
            from .local_media_info import inspect_local_media
            import folder_paths
            inspect=lambda name:inspect_local_media(name,folder_paths.get_input_directory())
        for slot,entry in entries.items():
            if slot.startswith('ref_video_') and not entry.get('muted',False):
                if inspect(entry['name'])['has_audio']:soundtracks+=1
        if target=='auto':
            index=max([int(slot.rsplit('_',1)[1]) for slot in audios],default=0)+1
            if index>3:raise ValueError('没有可在末尾追加的音频槽位；请明确选择要替换的 ref_audio 槽位。')
            slot=f'ref_audio_{index}'
        elif target in ('ref_audio_1','ref_audio_2','ref_audio_3'):
            slot=target
            if slot not in entries and audios and slot<audios[-1]:
                raise ValueError('该空槽插入会改变现有音频编号，请选择末尾空槽或明确替换已有槽。')
        else:raise ValueError('Ref2VA 请使用 ref_audio 槽位。')
        if (audios or soundtracks) and policy!='use_connected_audio':
            raise ValueError('已有参考音频或视频声轨。请明确选择“使用连接口播作为驱动”，保留其他参考素材。')
        replaced=slot if slot in entries else None
        ordinal=soundtracks+sorted(set(audios+[slot])).index(slot)+1
        label=f'<Audio {ordinal}>'
        if len(set(audios+[slot]))*frames>360:
            raise ValueError('现有逻辑会将独立参考音频对齐到视频时长，累计将超过 15 秒；请减少参考音频或缩短目标时长。')
        if len(set(entries)|{slot})>12:raise ValueError('加入新口播后参考文件超过 12 个，请减少素材。')
    else:
        if target not in ('auto','hybrid_audio'):raise ValueError('首尾帧口播只能接入 hybrid_audio。')
        slot='hybrid_audio';ordinal=1;label='<Audio 1>'
        if slot in entries:
            if policy!='use_connected_audio':raise ValueError('已有 Hybrid 音频，请明确选择使用连接口播替换它。')
            replaced=slot
    # Finish every validation before writing a file or loading any model.
    filename=store_audio(pcm)
    entry={'name':filename,'kind':'audio'}
    if slot in entries:active['media']=[[s,entry if s==slot else value] for s,value in active['media']]
    else:active['media'].append([slot,entry])
    return active,seconds,ordinal,{
        'source':'connected_audio','model_family':family,'source_seconds':samples/pcm.sample_rate,
        'selected_seconds':seconds,'frame_count':frames,'actual_seconds':frames/24,
        'padding_seconds':frames/24-samples/pcm.sample_rate,'truncated':False,
        'slot':slot,'label':label,'drive_audio_ordinal':ordinal,'replaced_slot':replaced,
        'audio_file':filename,'verified_lip_sync':False}


def verify_locked_bundle(integration,report):
    """Reject a mismatched decoded soundtrack before any sampler sees the graph."""
    import torch
    import folder_paths
    from .nodes import _load_audio_file
    root=Path(folder_paths.get_input_directory()).resolve();path=(root/report['audio_file']).resolve()
    if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest()!=path.stem:
        raise ValueError('连接口播文件已变化，请重新执行音频桥接。')
    expected=_load_audio_file(report['audio_file']);actual=integration.get('mux_audio')
    if not integration.get('is_original_audio') or actual is None or expected is None:
        raise ValueError('口播未成功锁定，采样已阻止。')
    a,e=actual['waveform'],expected['waveform'];count=e.shape[-1]
    if actual['sample_rate']!=expected['sample_rate'] or a.shape[:-1]!=e.shape[:-1] or a.shape[-1]<count:
        raise ValueError('锁定音频的采样率、声道或长度不匹配，采样已阻止。')
    if not torch.allclose(a[...,:count].cpu(),e.cpu(),rtol=0,atol=1e-6):
        raise ValueError('实际驱动源与连接口播不一致，采样已阻止。')
    if integration['length']!=report['frame_count'] or integration['length']>360:
        raise ValueError('实际视频帧数超出口播桥接预算。')
