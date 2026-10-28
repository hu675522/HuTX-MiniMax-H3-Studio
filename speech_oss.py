"""User-owned private OSS objects; signed URL valid for 10 minutes.

Only backend environment configuration is read. No OSS secret or URL is exposed
to widgets/reports. A finally block deletes the object, including failed uploads.
"""
import os
import re
import uuid
import json
import base64
import subprocess
from pathlib import Path
from contextlib import contextmanager
from .speech_errors import SpeechFailure

PREFIX='hutx-speech-temporary/'


def configured():
    return all(os.environ.get(name) for name in (
        'HUTX_SPEECH_OSS_BUCKET','HUTX_SPEECH_OSS_ACCESS_KEY_ID','HUTX_SPEECH_OSS_ACCESS_KEY_SECRET'))


def make_bucket():
    if not configured():raise SpeechFailure('oss_config')
    name=os.environ['HUTX_SPEECH_OSS_BUCKET']
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]',name):raise SpeechFailure('oss_config')
    from .speech_local import runtime_paths
    python=runtime_paths()[1]
    if not python.is_file():raise SpeechFailure('oss_config')
    return IsolatedBucket(python,name)


class IsolatedBucket:
    def __init__(self,python,name):self.python=python;self.name=name
    def call(self,action,key,data=None):
        # Secrets travel over stdin only, never process arguments or files.
        payload={'action':action,'key':key,'bucket':self.name,
                 'access_id':os.environ['HUTX_SPEECH_OSS_ACCESS_KEY_ID'],
                 'access_secret':os.environ['HUTX_SPEECH_OSS_ACCESS_KEY_SECRET'],
                 'token':os.environ.get('HUTX_SPEECH_OSS_SECURITY_TOKEN')}
        if data is not None:payload['data']=base64.b64encode(data).decode()
        try:
            result=subprocess.run([str(self.python),str(Path(__file__).with_name('speech_oss_worker.py'))],
                input=json.dumps(payload).encode(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:raise SpeechFailure('oss_upload')
            answer=json.loads(result.stdout)
            if not answer.get('ok'):raise SpeechFailure('oss_upload')
            return answer
        except Exception:raise SpeechFailure('oss_upload') from None
        finally:payload.clear()
    def put_object(self,key,data,headers=None):self.call('put',key,data)
    def sign_url(self,method,key,expires,slash_safe=True):return self.call('sign',key)['url']
    def delete_object(self,key):self.call('delete',key)


class ReferenceUpload:
    def __init__(self,bucket_factory=None):self.bucket_factory=bucket_factory or make_bucket

    @contextmanager
    def upload(self,wav,cancel):
        bucket=self.bucket_factory();key=PREFIX+uuid.uuid4().hex+'.wav'
        try:
            if cancel.is_set():
                from .speech_validation import SpeechCancelled
                raise SpeechCancelled()
            try:
                bucket.put_object(key,wav,headers={'Content-Type':'audio/wav','x-oss-object-acl':'private'})
                url=bucket.sign_url('GET',key,600,slash_safe=True)
            except Exception:raise SpeechFailure('oss_upload') from None
            yield url
        finally:
            # Do not honour cancellation here: cleanup must still run.
            try:bucket.delete_object(key)
            except Exception:raise SpeechFailure('oss_cleanup') from None
