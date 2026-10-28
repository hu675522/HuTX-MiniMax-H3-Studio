"""Speech-only environment/session/DPAPI credential boundary."""
import base64
import json
import os
import threading
from pathlib import Path
from .fal_credentials import WindowsDPAPI
from .speech_validation import SpeechError


def credential_path():
    import folder_paths
    return Path(folder_paths.get_user_directory())/'default/HuTX-MiniMax-H3-Studio/speech_dashscope.dat'


class SpeechCredentials:
    def __init__(self,path=credential_path,cipher=None):
        self.path=path;self.cipher=cipher or WindowsDPAPI();self.session='';self.lock=threading.RLock();self.generation=0

    def file(self):return Path(self.path() if callable(self.path) else self.path)

    def persisted(self):
        try:
            file=self.file()
            if not file.exists():return ''
            doc=json.loads(file.read_text(encoding='utf-8'))
            if doc['version']!=1:raise ValueError()
            payload=json.loads(self.cipher.decrypt(base64.b64decode(doc['encrypted_blob'],validate=True)))
            if payload['service']!='hutx-speech-dashscope':raise ValueError()
            return payload['key']
        except (ImportError,AttributeError):return ''
        except Exception:raise SpeechError('语音服务本机凭证不可用，请重新配置。') from None

    def resolve(self):
        with self.lock:
            value=os.environ.get('HUTX_SPEECH_DASHSCOPE_API_KEY','').strip() or os.environ.get('DASHSCOPE_API_KEY','').strip()
            if value:return value,'environment'
            if self.session:return self.session,'session'
            value=self.persisted()
            if value:return value,'persisted'
        raise SpeechError('请配置语音服务百炼 API Key 或 DASHSCOPE_API_KEY 环境变量。')

    def status(self):
        with self.lock:
            env=bool(os.environ.get('HUTX_SPEECH_DASHSCOPE_API_KEY','').strip() or os.environ.get('DASHSCOPE_API_KEY','').strip())
            unavailable=False
            try:persisted=bool(self.persisted())
            except SpeechError:persisted=False;unavailable=True
            source='environment' if env else 'session' if self.session else 'persisted' if persisted else 'none'
            return dict(configured=source!='none',active_source=source,environment_configured=env,
                session_configured=bool(self.session),persisted_configured=persisted,persistence_supported=self.cipher.supported,
                persisted_unavailable=unavailable)

    def save(self,key,storage):
        if not isinstance(key,str) or not key.strip() or len(key)>8192 or storage not in ('session','persisted'):
            raise SpeechError('请填写有效 API Key 并选择存储方式。')
        with self.lock:
            if storage=='session':self.session=key.strip()
            else:
                try:
                    payload=json.dumps({'service':'hutx-speech-dashscope','key':key.strip()}).encode()
                    blob=self.cipher.encrypt(payload);path=self.file();path.parent.mkdir(parents=True,exist_ok=True)
                    temp=path.with_suffix('.tmp')
                    temp.write_text(json.dumps({'version':1,'encrypted_blob':base64.b64encode(blob).decode()}),encoding='utf-8')
                    os.replace(temp,path)
                except Exception:raise SpeechError('语音服务安全保存失败；当前系统可改用会话凭证。') from None
            self.generation+=1

    def delete(self):
        with self.lock:
            try:self.file().unlink(missing_ok=True);self.generation+=1
            except Exception:raise SpeechError('无法删除本机语音凭证。') from None


SPEECH_CREDENTIALS=SpeechCredentials()
