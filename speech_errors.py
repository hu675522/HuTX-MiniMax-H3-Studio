"""Only fixed, credential-free error codes cross provider boundaries."""
from .speech_validation import SpeechError

MESSAGES={
 'invalid_credential':'语音 API Key 无效，请重新配置。',
 'permission':'语音服务权限或地域不匹配，请检查北京地域配置。',
 'rate_limit':'语音服务限流，请稍后手动重试。',
 'timeout':'语音请求超时，服务端可能已处理；未自动重试。',
 'network':'语音网络请求失败，未自动重试。',
 'registration':'音色注册失败，请检查录音质量和模型权限。',
 'voice_invalid':'音色已失效，请点击重新生成以重新注册。',
 'provider':'语音服务处理失败，未自动重试。',
 'oss_config':'云端克隆需要配置本机 OSS 上传环境；请查看语音部署说明。',
 'oss_upload':'参考录音上传失败，请检查 OSS 权限或网络。',
 'oss_cleanup':'临时录音清理失败，请检查 OSS DeleteObject 权限；临时对象仍需清理。',
 'reference_silent':'参考录音为静音或音量过低，请重新录制。',
 'reference_speech':'参考录音未检测到足够的连续人声，请提供清晰朗读录音。',
 'reference_transcript':'参考录音自动识别失败，或缺少本地识别模型；请检查本地环境或更换清晰录音。',
 'local_timeout':'本地语音生成超时，进程已停止。',
 'local_failure':'本地语音生成失败，请检查独立环境与参考录音。',
 'queue_busy':'ComfyUI 队列正在运行，请待任务结束后生成本地口播。',
 'queue_unsupported':'当前 ComfyUI 队列无法安全协调本地预览，请通过工作流队列生成口播。',
}

class SpeechFailure(SpeechError):
    def __init__(self,code):
        self.code=code if code in MESSAGES else 'provider'
        super().__init__(MESSAGES[self.code])
