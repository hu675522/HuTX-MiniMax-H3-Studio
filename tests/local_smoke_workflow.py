"""Opt-in local-only API workflow generator and smoke runner. No pytest inference."""
import json
from pathlib import Path
import time
import urllib.request
import sys


def workflow(task):
    media = {'t2va': {}, 'i2va': {'first_frame': '01.png'}, 'l2va': {'last_frame': '02.png'},
             'fl2va': {'first_frame': '01.png', 'last_frame': '02.png'},
             'ref2va': {'ref_image_1': '01.png', 'ref_video_1': '01.mp4', 'ref_audio_1': '01.WAV'}}[task]
    inputs = dict(model_name='minimax_h3_' + ('ref2va' if task == 'ref2va' else 'fl2va') + '_pruned_int8_convrot.safetensors',
                  clip_name='qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors',
                  video_vae_name='minimax_h3_video_vae_fp16.safetensors', audio_vae_name='minimax_h3_audio_vae_fp32.safetensors',
                  aspect='16:9', megapixels=0.5, duration_seconds=5,
                  main_mode='all_reference' if task == 'ref2va' else 'text_keyframes',
                  prompt='A calm scene with gentle natural motion, a steady camera and ambient sound.', **media)
    def node(kind, **values): return {'class_type': kind, 'inputs': values}
    graph = {
        '1': node('GHLocalVideoInputGH', **inputs),
        '2': node('MiniMaxH3IntegrationAdapterGH', integration=['1', 1]),
        '3': node('LoraLoaderModelOnly', model=['1', 0], lora_name='minimax_h3_fl2v_turbo_4step_v1.1_768p_comfyui_bf16.safetensors', strength_model=1.0),
        '4': node('MiniMaxH3DualClockT8GH', model=['3', 0], av_latent=['2', 1], steps=4, shift_video=12.0, shift_audio=3.0,
                  sampler_name='dual_clock_euler', scheduler='native_flow'),
        '5': node('BasicGuider', model=['4', 0], conditioning=['2', 0]),
        '6': node('RandomNoise', noise_seed=1),
        '7': node('SamplerCustomAdvanced', noise=['6', 0], guider=['5', 0], sampler=['4', 1], sigmas=['4', 2], latent_image=['2', 1]),
        '8': node('MiniMaxH3AVDecodeT8GH', av_latent=['7', 0], video_vae=['2', 2], audio_vae=['2', 3]),
        '9': node('CreateVideo', images=['8', 0], audio=['2', 5] if task == 'ref2va' else ['8', 1], fps=24.0),
        '10': node('SaveVideo', video=['9', 0], filename_prefix='local_v030/' + task, format='auto', **{'format.codec': 'auto'}),
    }
    if task == 'ref2va':
        graph.pop('3')
        graph['4']['inputs'].update(model=['1', 0], steps=20, sampler_name='res_multistep', scheduler='beta')
    return graph


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1] / '.local-smoke-v030'
    root.mkdir(exist_ok=True)
    def request(path, value=None):
        req = urllib.request.Request('http://127.0.0.1:8190' + path,
            data=json.dumps(value).encode() if value is not None else None, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=30) as response: return json.load(response)
    results = json.loads((root / 'results.json').read_text(encoding='utf-8')) if (root / 'results.json').exists() else []
    for task in (sys.argv[1:] or ('t2va', 'i2va', 'l2va', 'fl2va', 'ref2va')):
        while request('/queue')['queue_running']:
            time.sleep(5)
        graph = workflow(task)
        (root / (task + '-api.json')).write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')
        start = time.monotonic()
        record = {'task': task, 'model': graph['1']['inputs']['model_name'], 'lora': graph.get('3', {}).get('inputs', {}).get('lora_name', 'none (existing Ref2VA workflow)'),
                  'width': 960, 'height': 544, 'frames': 124, 'fps': 24, 'steps': graph['4']['inputs']['steps'], 'seed': 1,
                  'sampler': graph['4']['inputs']['sampler_name'], 'scheduler': graph['4']['inputs']['scheduler'],
                  'vram_mode': 'ComfyUI default DynamicVRAM (same host setting)'}
        try:
            queued = request('/prompt', {'prompt': graph, 'client_id': 'hutx-local-v030-smoke'})
            record['prompt_id'] = queued['prompt_id']
            print(task + ' queued ' + record['prompt_id'], flush=True)
            while True:
                history = request('/history/' + record['prompt_id']).get(record['prompt_id'])
                if history:
                    record['status'] = history['status']; record['outputs'] = history.get('outputs', {})
                    (root / (task + '-history.json')).write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding='utf-8')
                    break
                if time.monotonic() - start > 1800:
                    request('/interrupt', {}); record['status'] = 'local smoke timeout (1800s)'; break
                time.sleep(5)
        except Exception as error:
            record['error'] = str(error)
            if hasattr(error, 'read'): record['validation'] = error.read().decode('utf-8')
        record['queue_elapsed_seconds'] = round(time.monotonic() - start, 2)
        results = [r for r in results if r['task'] != task] + [record]
        (root / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print(task + ' finished ' + str(record.get('status', record.get('error')))[:300], flush=True)
