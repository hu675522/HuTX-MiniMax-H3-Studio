"""Opt-in V0.3.1: mock optimizer -> persisted Local UI state -> real local sampler.

Uses only localhost:8190 and the existing V0.3.0 T2VA/I2VA settings.
"""
import json
from pathlib import Path
import subprocess
import time
import urllib.request
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_smoke_workflow import workflow


def request(path, data=None):
    req=urllib.request.Request('http://127.0.0.1:8190'+path,
        data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=30) as response:return json.load(response)


if __name__=='__main__':
    repo=Path(__file__).resolve().parents[1]
    output=repo/'.local-smoke-v031';output.mkdir(exist_ok=True)
    results=[]
    for task in ('t2va','i2va'):
        graph=workflow(task)
        prompt=graph['1']['inputs']['prompt']
        if task=='i2va':prompt='<Picture 1> '+prompt
        initial={'schema_version':1,'mode':'text_keyframes','prompt':prompt,
                 'media':[] if task=='t2va' else [['first_frame',{'name':'01.png','kind':'image'}]],
                 'optimizer':{'config':{'auto_optimize':True,'read_media':False,'prompt_profile':'auto'}}}
        # Actual shared controller queue wrapper, provider fully intercepted by fixture.
        mocked=json.loads(subprocess.run(['node',str(repo/'tests/frontend_local_video_fixture.mjs')],
            input=json.dumps({'state':initial,'optimizedPrompt':prompt,'actions':[{'type':'auto'}]}),
            text=True,encoding='utf-8',capture_output=True,check=True).stdout)
        assert mocked['queued']==1 and mocked['results']==[True]
        graph['1']['inputs']['gh_local_state_json']=json.dumps(mocked['state'],ensure_ascii=False)
        graph['1']['inputs']['prompt']=mocked['state']['prompt']
        graph['10']['inputs']['filename_prefix']='local_v031/'+task
        (output/(task+'-api.json')).write_text(json.dumps(graph,ensure_ascii=False,indent=2),encoding='utf-8')
        queue=request('/queue')
        if queue['queue_running'] or queue['queue_pending']:raise RuntimeError('Isolated queue must be empty.')
        started=time.monotonic();queued=request('/prompt',{'prompt':graph,'client_id':'hutx-local-v031-smoke'})
        print(task+' queued '+queued['prompt_id'],flush=True)
        while True:
            history=request('/history/'+queued['prompt_id']).get(queued['prompt_id'])
            if history:break
            if time.monotonic()-started>1800:
                request('/interrupt',{});raise RuntimeError('Local smoke timeout.')
            time.sleep(5)
        (output/(task+'-history.json')).write_text(json.dumps(history,ensure_ascii=False,indent=2),encoding='utf-8')
        result={'task':task,'status':history['status'],'elapsed_seconds':round(time.monotonic()-started,3),
                'outputs':history.get('outputs',{}),'mock_optimizer_profile':'structured','prompt_id':queued['prompt_id']}
        results.append(result);(output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(task+' '+history['status']['status_str']+' '+str(result['elapsed_seconds'])+'s',flush=True)
        if history['status']['status_str']!='success':raise RuntimeError('Local smoke failed; inspect saved history.')
