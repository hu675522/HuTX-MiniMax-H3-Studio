"""Beijing-only HTTP adapter. No retries after uncertain chargeable requests."""
import hashlib
import io
import json
import re
import threading
import time
import uuid
from urllib.parse import urlparse

from ..speech_validation import SpeechError, SpeechCancelled
from ..speech_credentials import SPEECH_CREDENTIALS
from ..speech_errors import SpeechFailure
from ..speech_oss import ReferenceUpload

_VOICE_PRESETS = [
    # Keep the first two IDs stable for existing workflows.
    {'id':'cloud:longanyang','name':'普通话 · 阳光男声（龙安洋）','group':'中文 · 普通话','model':'cosyvoice-v3-flash','voice':'longanyang'},
    {'id':'cloud:longanhuan_v3','name':'普通话 · 元气女声（龙安欢）','group':'中文 · 普通话','model':'cosyvoice-v3-flash','voice':'longanhuan_v3'},
    {'id':'cloud:cosy:longfei_v3:zh','name':'普通话 · 磁性男声（龙飞）','group':'中文 · 普通话','model':'cosyvoice-v3-flash','voice':'longfei_v3'},
    {'id':'cloud:cosy:longyingxiao_v3:zh','name':'普通话 · 清甜女声（龙应笑）','group':'中文 · 普通话','model':'cosyvoice-v3-flash','voice':'longyingxiao_v3'},
    {'id':'cloud:cosy:longjiaxin_v3:yue','name':'粤语 · 优雅女声（龙嘉欣）','group':'中文 · 地方方言','model':'cosyvoice-v3-flash','voice':'longjiaxin_v3'},
    {'id':'cloud:cosy:longanyue_v3:yue','name':'粤语 · 欢脱男声（龙安粤）','group':'中文 · 地方方言','model':'cosyvoice-v3-flash','voice':'longanyue_v3'},
    {'id':'cloud:cosy:longlaotie_v3:db','name':'东北话 · 直率男声（龙老铁）','group':'中文 · 地方方言','model':'cosyvoice-v3-flash','voice':'longlaotie_v3'},
    {'id':'cloud:cosy:longshange_v3:sx','name':'陕西话 · 原味男声（龙陕哥）','group':'中文 · 地方方言','model':'cosyvoice-v3-flash','voice':'longshange_v3'},
    {'id':'cloud:cosy:longanmin_v3:mn','name':'闽南话 · 清甜女声（龙安闽）','group':'中文 · 地方方言','model':'cosyvoice-v3-flash','voice':'longanmin_v3'},
    {'id':'cloud:cosy:longanhuan_v3:sc','name':'四川话 · 元气女声（龙安欢）','group':'中文 · 地方方言','model':'cosyvoice-v3-flash','voice':'longanhuan_v3','instruction':'请用四川话表达。'},
    {'id':'cloud:cosy:loongabby_v3:en','name':'English · American Female（Abby）','group':'English','model':'cosyvoice-v3-flash','voice':'loongabby_v3','language_hints':['en']},
    {'id':'cloud:cosy:loongandy_v3:en','name':'English · American Male（Andy）','group':'English','model':'cosyvoice-v3-flash','voice':'loongandy_v3','language_hints':['en']},
    {'id':'cloud:cosy:loongriko_v3:ja','name':'日本語 · アニメ女声（Riko）','group':'日本語','model':'cosyvoice-v3-flash','voice':'loongriko_v3','language_hints':['ja']},
    {'id':'cloud:cosy:loongtomoya_v3:ja','name':'日本語 · 落ち着いた男声（Tomoya）','group':'日本語','model':'cosyvoice-v3-flash','voice':'loongtomoya_v3','language_hints':['ja']},
    {'id':'cloud:qwen31:longanlingxin_v3.1:fr','name':'Français · Voix féminine（Lingxin）','group':'Français','model':'qwen-audio-3.1-tts-flash','voice':'longanlingxin_v3.1','language_hints':['fr']},
    {'id':'cloud:qwen31:xunanchuan:fr','name':'Français · Voix masculine（Nanchuan）','group':'Français','model':'qwen-audio-3.1-tts-flash','voice':'xunanchuan','language_hints':['fr']},
    {'id':'cloud:qwen31:longanlingxin_v3.1:de','name':'Deutsch · Weibliche Stimme（Lingxin）','group':'Deutsch','model':'qwen-audio-3.1-tts-flash','voice':'longanlingxin_v3.1','language_hints':['de']},
    {'id':'cloud:qwen31:xunanchuan:de','name':'Deutsch · Männliche Stimme（Nanchuan）','group':'Deutsch','model':'qwen-audio-3.1-tts-flash','voice':'xunanchuan','language_hints':['de']},
    {'id':'cloud:qwen31:longanlingxin_v3.1:it','name':'Italiano · Voce femminile（Lingxin）','group':'Italiano','model':'qwen-audio-3.1-tts-flash','voice':'longanlingxin_v3.1','language_hints':['it']},
    {'id':'cloud:qwen31:xunanchuan:it','name':'Italiano · Voce maschile（Nanchuan）','group':'Italiano','model':'qwen-audio-3.1-tts-flash','voice':'xunanchuan','language_hints':['it']},
]
VOICES = [{key:value for key,value in preset.items() if key in ('id','name','group')} for preset in _VOICE_PRESETS]
VOICE_PRESETS = {preset['id']:preset for preset in _VOICE_PRESETS}


def endpoint(workspace=''):
    if not isinstance(workspace,str):raise SpeechError('百炼业务空间 ID 无效。')
    if workspace and not re.fullmatch(r'[a-zA-Z0-9-]{1,80}',workspace):raise SpeechError('百炼业务空间 ID 无效。')
    host=workspace+'.cn-beijing.maas.aliyuncs.com' if workspace else 'dashscope.aliyuncs.com'
    return 'https://'+host+'/api/v1'


class Transport:
    def request(self,method,url,*,key=None,payload=None,params=None,files=None,form=None,cancel=None,binary=False,resolve_oss=False):
        import requests
        parsed=urlparse(url)
        if parsed.scheme!='https' or not parsed.hostname or not parsed.hostname.endswith('.aliyuncs.com') or parsed.username or parsed.port not in (None,443):
            raise SpeechError('服务返回了不支持的音频地址。')
        if cancel and cancel.is_set():raise SpeechCancelled()
        headers={'Authorization':'Bearer '+key} if key else {}
        if resolve_oss:headers['X-DashScope-OssResourceResolve']='enable'
        try:
            with requests.request(method,url,headers=headers,json=payload,params=params,files=files,data=form,
                timeout=(10,30),allow_redirects=False,stream=True) as response:
                if response.status_code!=200:
                    codes={401:'invalid_credential',403:'permission',429:'rate_limit'}
                    if url.endswith('/SpeechSynthesizer'):codes[404]='voice_invalid'
                    code=codes.get(response.status_code)
                    if code is None:
                        code='registration' if url.endswith('/customization') else 'provider'
                        # Parse only a bounded error code; never return provider text.
                        error_bytes=next(response.iter_content(4096),b'')[:4096]
                        try:provider_code=json.loads(error_bytes).get('code','')
                        except Exception:provider_code=''
                        if provider_code in ('VoiceNotFound','InvalidVoice','VoiceNotExist'):code='voice_invalid'
                    raise SpeechFailure(code)
                data=bytearray();limit=100_000_000 if binary else 2_000_000
                for chunk in response.iter_content(65536):
                    if cancel and cancel.is_set():raise SpeechCancelled()
                    data.extend(chunk)
                    if len(data)>limit:raise SpeechError('语音响应超过大小限制。')
                return bytes(data) if binary else json.loads(data) if data else {}
        except (SpeechError,SpeechCancelled):raise
        except requests.exceptions.Timeout:raise SpeechFailure('timeout') from None
        except Exception:raise SpeechFailure('network') from None


class BailianSpeechProvider:
    version='bailian-beijing-http-v1'
    def __init__(self,transport=None,credentials=None,uploader=None):
        self.transport=transport or Transport();self.credentials=credentials or SPEECH_CREDENTIALS
        self.uploader=uploader or ReferenceUpload()
        self.voices={};self.lock=threading.Lock()

    def scope(self):
        key,_=self.credentials.resolve()
        return hashlib.sha256(key.encode()).hexdigest()

    def synthesize(self,request,reference,cancel):
        from ..speech_service import wav_bytes,decode_wav
        key,_=self.credentials.resolve();base=endpoint(request.get('workspace',''))
        model=request.get('cloud_model','auto')
        if model=='auto':model='cosyvoice-v3.5-plus' if request['mode']=='clone' else 'cosyvoice-v3-flash'
        if request['mode']=='preset':
            preset=VOICE_PRESETS.get(request['voice'])
            if not preset:raise SpeechError('请选择当前云端支持的系统音色。')
            if request.get('cloud_model','auto') not in ('auto',preset['model']):
                raise SpeechError('所选系统音色与云端模型不匹配，请使用自动选择。')
            model,voice=preset['model'],preset['voice']
        else:
            from ..speech_quality import check_reference_energy
            check_reference_energy(reference)
            if model not in ('cosyvoice-v3.5-plus','cosyvoice-v3.5-flash'):raise SpeechError('请选择支持的声音克隆模型。')
            if not 5 <= reference.seconds <= 60 or reference.sample_rate<16000:
                raise SpeechError('云端克隆请提供 5～60 秒、至少 16kHz 的清晰录音，推荐 10～20 秒。')
            wav=wav_bytes(reference)
            if len(wav)>10_000_000:raise SpeechError('云端克隆参考音频需小于 10MB。')
            identity=hashlib.sha256(key.encode()+base.encode()+model.encode()+wav).hexdigest()
            # Bind voice IDs to account, workspace, model and audio content.
            with self.lock:
                voice=self.voices.get(identity)
                if not voice:
                    with self.uploader.upload(wav,cancel) as url:
                        data=self.transport.request('POST',base+'/services/audio/tts/customization',key=key,
                            payload={'model':'voice-enrollment','input':{'action':'create_voice','target_model':model,'prefix':'hutx','url':url}},cancel=cancel)
                    voice=data['output']['voice_id']
                    if not isinstance(voice,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}',voice):raise SpeechError('音色注册响应无效。')
                    self.voices[identity]=voice
                    if len(self.voices)>100:self.voices.pop(next(iter(self.voices)))
        if cancel.is_set():raise SpeechCancelled()
        try:
            synth_input={'text':request['text'],'voice':voice,'format':'wav','sample_rate':24000,
                         ('rate' if model.startswith('qwen-audio-') else 'speech_rate'):request['speed']}
            if request['mode']=='preset':
                if preset.get('language_hints'):synth_input['language_hints']=preset['language_hints']
                if preset.get('instruction'):synth_input['instruction']=preset['instruction']
            result=self.transport.request('POST',base+'/services/audio/tts/SpeechSynthesizer',key=key,cancel=cancel,
                payload={'model':model,'input':synth_input})
        except SpeechFailure as exc:
            if exc.code=='voice_invalid' and request['mode']=='clone':
                with self.lock:self.voices.pop(identity,None)
            raise
        output=result.get('output',{});audio=output.get('audio',{})
        url=audio.get('url') if isinstance(audio,dict) else None
        if not url:url=output.get('audio_url')
        if not isinstance(url,str):raise SpeechError('百炼未返回可下载的音频。')
        # Official examples can return an OSS HTTP URL; download over TLS only.
        parsed=urlparse(url)
        if parsed.scheme=='http' and parsed.hostname and parsed.hostname.endswith('.aliyuncs.com') and parsed.port is None:
            url=parsed._replace(scheme='https').geturl()
        # Never attach an API key to the audio download.
        return decode_wav(self.transport.request('GET',url,binary=True,cancel=cancel))
