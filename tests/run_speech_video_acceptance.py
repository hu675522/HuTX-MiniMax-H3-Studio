"""Opt-in local H3 acceptance. Existing audio only; never calls TTS or cloud."""
import json
import sys
import time
import urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from local_smoke_workflow import workflow

ROOT=Path(__file__).resolve().parents[1]/'.local-smoke-v040'

def request(path,data=None):
    req=urllib.request.Request('http://127.0.0.1:8190'+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=30) as response:return json.load(response)

def build(task,portrait=False):
    graph=workflow(task)
    if '3' in graph:
        graph['3']['inputs']['lora_name']='minimax_h3_fl2v_turbo_4step_v1.2_768p_comfyui_bf16.safetensors'
    values=graph['1']['inputs']
    for name in list(values):
        if name.startswith('ref_') or name in ('first_frame','last_frame'):values.pop(name)
    values.update(driver_audio=['11',0],driver_model_family='Ref2VA' if task=='ref2va' else 'FL2VA',
        driver_conflict='reject_conflicts',driver_slot='auto',duration_seconds=5,
        prompt='<Picture 1> 正面面对镜头自然口播，按照输入的驱动音频同步说话，保持人物身份和固定镜头。')
    if task=='ref2va':values['ref_image_1']='person.png'
    else:values['first_frame']='person.png'
    if task=='fl2va':values['last_frame']='person.png'
    if portrait:
        values.update(aspect='adaptive',prompt='<Picture 1> A single continuous portrait shot of the same man speaking directly to the camera. His full head and shoulders stay visible throughout. He speaks the supplied audio naturally, moving his lips and jaw with the speech. The camera and dark background remain still. Only the man is visible, with no cuts, titles, graphics, subtitles or transitions.')
    graph['11']={'class_type':'LoadAudio','inputs':{'audio':'speech.wav'}}
    graph['9']['inputs']['audio']=['2',5]
    graph['10']['inputs']['filename_prefix']='speech_acceptance/'+task+('_portrait' if portrait else '')
    return graph

if __name__=='__main__':
    portrait='--portrait' in sys.argv
    if portrait:sys.argv.remove('--portrait')
    result_path=ROOT/('speech-results'+('-portrait' if portrait else '')+'.json')
    results=json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else []
    for task in sys.argv[1:] or ('i2va','fl2va','ref2va'):
        queue=request('/queue')
        if queue['queue_running'] or queue['queue_pending']:raise RuntimeError('Isolated queue not empty')
        graph=build(task,portrait);label=task+('_portrait' if portrait else '')
        (ROOT/(label+'-api.json')).write_text(json.dumps(graph,ensure_ascii=False,indent=2),encoding='utf-8')
        start=time.monotonic()
        queued=request('/prompt',{'prompt':graph,'client_id':'hutx-stage6-local'})
        print(task+' queued '+queued['prompt_id'],flush=True)
        while True:
            history=request('/history/'+queued['prompt_id']).get(queued['prompt_id'])
            if history:break
            if time.monotonic()-start>1800:
                request('/interrupt',{});raise RuntimeError('Isolated acceptance exceeded 1800s')
            time.sleep(3)
        (ROOT/(label+'-history.json')).write_text(json.dumps(history,ensure_ascii=False,indent=2),encoding='utf-8')
        result={'task':task,'status':history['status']['status_str'],'elapsed_seconds':round(time.monotonic()-start,2),
            'prompt_id':queued['prompt_id'],'outputs':history.get('outputs',{}),'lip_sync_acceptance':'pending'}
        results=[old for old in results if old['task']!=task]+[result]
        result_path.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(task+' '+result['status']+' '+str(result['elapsed_seconds'])+'s',flush=True)
        if result['status']!='success':raise RuntimeError('Inspect local history; no automatic retry')
