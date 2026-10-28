import json
from pathlib import Path
import shutil
import subprocess

from hutx_minimax_h3_testpkg.local_video_state import local_state, execution_state

ROOT=Path(__file__).resolve().parents[1]


def run(**data):
    return json.loads(subprocess.run([shutil.which('node'),str(ROOT/'tests/frontend_local_video_fixture.mjs')],
        input=json.dumps(data),text=True,encoding='utf-8',capture_output=True,check=True).stdout)


def test_upload_save_reload_and_mode_isolation():
    result=run(actions=[{'type':'upload','slot':'first_frame'},{'type':'prompt','value':'<Picture 1> turns.'},
        {'type':'reload'},{'type':'mode','value':'all_reference'},{'type':'upload','slot':'ref_image_3'},
        {'type':'reload'},{'type':'mode','value':'text_keyframes'}])
    assert [r['url'] for r in result['requests'] if r['url']=='/upload/image']==['/upload/image','/upload/image']
    snapshots=result['snapshots']
    assert snapshots[2]['state']['prompt']=='<Picture 1> turns.'
    assert snapshots[2]['rows']==['first_frame','last_frame','hybrid_audio']
    assert len(snapshots[3]['rows'])==15
    for snapshot in snapshots:
        assert local_state(snapshot['state'])==snapshot['state']
        assert json.loads(snapshot['properties']['gh_local_video_state'])==snapshot['state']
    assert execution_state(result['state'])[1]=='i2va'
    assert [s for s,_ in result['state']['media']]==['first_frame','ref_image_3']


def test_removal_is_authoritative_and_configure_restores_prompt():
    state={'schema_version':1,'mode':'text_keyframes','prompt':'Loaded',
           'media':[['last_frame',{'name':'tail.png','kind':'image'}]]}
    result=run(actions=[{'type':'configure','state':state},{'type':'reload'},{'type':'remove','slot':'last_frame'},{'type':'reload'}])
    assert execution_state(result['snapshots'][1]['state'])[1]=='l2va'
    assert result['state']['media']==[] and result['state']['prompt']=='Loaded'
    assert dict(result['snapshots'][-1]['widgets'])['last_frame']==''


def test_new_frontend_scope_reuses_ux_without_cloud_execution():
    source=(ROOT/'web/js/gh_local_video_input.js').read_text(encoding='utf-8')
    for marker in ('GHCloudVideoInputGH','MiniMaxH3IntegrationGH','GHVideoRequest','localStorage','sessionStorage'):
        assert marker not in source
    for marker in ('createPromptOptimizerController','attachCloudMediaPicker','createMediaCard','bindResponsiveDomHost'):
        assert marker in source
    assert "['GHLocalVideoInputGH','GHLocalVideoInputDualEngineGH'].includes(nodeData.name)" in source
