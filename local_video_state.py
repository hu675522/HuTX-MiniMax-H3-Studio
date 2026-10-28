"""Small, JSON-only Local UI boundary; no Cloud/Fal request types."""
from __future__ import annotations

import json
import math
from pathlib import PurePosixPath

ASPECTS = ('adaptive', '21:9', '16:9', '4:3', '1:1', '3:4', '9:16')
IMAGE_SLOTS = ('first_frame', 'last_frame', *(f'ref_image_{i}' for i in range(1, 10)))
VIDEO_SLOTS = tuple(f'ref_video_{i}' for i in range(1, 4))
AUDIO_SLOTS = ('hybrid_audio', *(f'ref_audio_{i}' for i in range(1, 4)))
MEDIA_SLOTS = (*IMAGE_SLOTS, *VIDEO_SLOTS, *AUDIO_SLOTS)


def media_kind(slot):
    return 'image' if slot in IMAGE_SLOTS else 'video' if slot in VIDEO_SLOTS else 'audio'


def local_state(raw='', *, mode='text_keyframes', prompt='', media=None):
    state = json.loads(raw) if isinstance(raw, str) and raw else raw or {}
    if not isinstance(state, dict) or set(state) - {'schema_version', 'mode', 'prompt', 'media', 'optimizer', 'ui'}:
        raise ValueError('Invalid Local state fields.')
    if type(state.get('schema_version', 1)) is not int or state.get('schema_version', 1) != 1:
        raise ValueError('Unsupported Local state version.')
    mode, prompt = state.get('mode', mode), state.get('prompt', prompt)
    if mode not in ('text_keyframes', 'all_reference') or not isinstance(prompt, str):
        raise ValueError('Invalid Local mode/prompt.')
    entries = state.get('media', [[s, {'name': n, 'kind': media_kind(s)}] for s, n in (media or {}).items() if n and n != '(none)'])
    if not isinstance(entries, list):
        raise ValueError('Local media must be a slot list.')
    output, seen = [], set()
    for item in entries:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError('Invalid Local media entry.')
        slot, entry = item
        if not isinstance(slot, str) or slot not in MEDIA_SLOTS or slot in seen:
            raise ValueError('Invalid or duplicate Local media slot.')
        seen.add(slot)
        allowed = {'name', 'kind'} | ({'muted'} if slot in VIDEO_SLOTS else {'trimStart', 'trimEnd'} if slot in AUDIO_SLOTS else set())
        if not isinstance(entry, dict) or set(entry) - allowed or entry.get('kind', media_kind(slot)) != media_kind(slot):
            raise ValueError('Invalid Local media fields.')
        name = entry.get('name')
        if not isinstance(name, str) or not name or '\x00' in name:
            raise ValueError('Local media needs an input-relative filename.')
        name = name.replace('\\', '/')
        if name.startswith('/') or ':' in name or any(p in ('', '.', '..') for p in name.split('/')):
            raise ValueError('Local media must stay in the ComfyUI input directory.')
        if name.endswith((' [input]', ' [output]', ' [temp]')):
            raise ValueError('Annotated Local paths are not supported.')
        clean = {**entry, 'name': str(PurePosixPath(name)), 'kind': media_kind(slot)}
        if 'muted' in clean and type(clean['muted']) is not bool:
            raise ValueError('Local video muted must be boolean.')
        start = clean.get('trimStart', 0)
        end = clean.get('trimEnd')
        for value in (start, end):
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise ValueError('Invalid Local audio trim range.')
        if end is not None and end <= start:
            raise ValueError('Local audio trim end must exceed start.')
        output.append([slot, clean])
    result = {'schema_version': 1, 'mode': mode, 'prompt': prompt, 'media': output}
    if 'optimizer' in state:
        result['optimizer'] = local_optimizer_state(state['optimizer'])
    if 'ui' in state:
        if not isinstance(state['ui'], dict) or set(state['ui']) - {'models_collapsed'} or any(type(v) is not bool for v in state['ui'].values()):
            raise ValueError('Invalid Local UI state.')
        result['ui'] = dict(state['ui'])
    if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > 1048576:
        raise ValueError('Local state exceeds 1 MiB; nothing was truncated.')
    return result


def local_optimizer_state(value):
    from .prompt_optimizer.config_schema import assert_optimizer_persistence_safe, serialize_public_optimizer_config, OPTIMIZER_STATE_VERSION
    assert_optimizer_persistence_safe(value, 'local.optimizer')
    allowed = {'optimizer_state_version', 'config', 'original_prompt', 'optimized_prompt', 'optimizer_report', 'report'}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError('Invalid Local optimizer fields.')
    version = value.get('optimizer_state_version', 1)
    if type(version) is not int or version not in (1, OPTIMIZER_STATE_VERSION):
        raise ValueError('Unsupported optimizer_state_version.')
    result = dict(value)
    if 'config' in value:
        result['config'] = serialize_public_optimizer_config(value['config'], allow_derived=version == 1)
    for key in ('report', 'optimizer_report'):
        if key in value and not isinstance(value[key], str):
            raise ValueError('Local optimizer report must be a string.')
    if 'original_prompt' in value or 'optimized_prompt' in value:
        pair = {key: value.get(key) for key in ('original_prompt', 'optimized_prompt')}
        if any(not isinstance(text, str) for text in pair.values()):
            raise ValueError('Prompt history before/after must both be strings.')
        if len(json.dumps(pair, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) > 262144:
            raise ValueError('Prompt history exceeds 256 KiB; no text was truncated.')
    return result


def execution_state(state):
    """Inactive uploads persist in UI but never load/condition the active task."""
    reference = state['mode'] == 'all_reference'
    active = [[slot, entry] for slot, entry in state['media'] if slot.startswith('ref_') == reference]
    names = {slot for slot, _ in active}
    if reference:
        if not active:
            raise ValueError('Ref2VA requires reference media / 全能参考至少需要一个素材。')
        task = 'ref2va'
    else:
        first, last = 'first_frame' in names, 'last_frame' in names
        if 'hybrid_audio' in names and not (first or last):
            raise ValueError('Local Hybrid audio requires a first or last frame.')
        task = 'fl2va' if first and last else 'i2va' if first else 'l2va' if last else 't2va'
    # Only the legacy input fields cross into conditioning/model graph caches.
    return {key: active if key == 'media' else state[key] for key in ('schema_version', 'mode', 'prompt', 'media')}, task
