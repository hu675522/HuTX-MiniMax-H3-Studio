// Shared state/timing controller for the stage-two mock preview.
const SAFE_ERRORS={
    reference_transcript:'参考录音自动识别失败，或缺少本地识别模型；请检查本地环境或更换清晰录音。',
    invalid_credential:'语音 API Key 无效，请重新配置。',permission:'语音服务权限或地域不匹配，请检查北京地域配置。',
    rate_limit:'语音服务限流，请稍后手动重试。',timeout:'语音请求超时，服务端可能已处理；未自动重试。',
    network:'语音网络请求失败，未自动重试。',registration:'音色注册失败，请检查录音质量和模型权限。',
    voice_invalid:'音色已失效，请点击重新生成以重新注册。',provider:'语音服务处理失败，未自动重试。',
    oss_config:'云端克隆需要配置本机 OSS 上传环境；请查看语音部署说明。',oss_upload:'参考录音上传失败，请检查 OSS 权限或网络。',
    oss_cleanup:'临时录音清理失败，请检查 OSS DeleteObject 权限；临时对象仍需清理。',
    reference_silent:'参考录音为静音或音量过低，请重新录制。',reference_speech:'参考录音未检测到足够的连续人声，请提供清晰朗读录音。',
    local_timeout:'本地语音生成超时，进程已停止。',local_failure:'本地语音生成失败，请检查独立环境与参考录音。',
    queue_busy:'ComfyUI 队列正在运行，请待任务结束后生成本地口播。',queue_unsupported:'当前 ComfyUI 队列无法安全协调本地预览，请通过工作流队列生成口播。'
};
export function createSpeechController({send, changed = () => {}, now = () => performance.now()}) {
    const state = {status:'idle', elapsed:0, result:null, stale:false, adopted:false, message:''};
    let timer = null, running = null, requestId = null, revision = 0, disposed = false;
    const emit = () => {if(!disposed) changed({...state});};
    function finish(status, message, started) {
        clearInterval(timer); timer=null;
        state.status=status;state.message=message;state.elapsed=(now()-started)/1000;emit();
    }
    function generate(parameters, referenceFile='') {
        if(running) return running;
        const capturedRevision=revision, started=now();
        requestId=typeof crypto.randomUUID==='function' ? crypto.randomUUID()
            : Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');
        const id=requestId;
        Object.assign(state,{status:'running',elapsed:0,result:null,adopted:false,stale:false,message:''});emit();
        timer=setInterval(()=>{state.elapsed=(now()-started)/1000;emit();},100);
        running=(async()=>{
            try {
                const result=await send('/generate',{request_id:id,parameters,reference_file:referenceFile});
                if(state.status==='cancelled' || capturedRevision!==revision) return null;
                state.result=result;finish('success',result.report?.is_mock?'Mock 测试音已生成，请试听后采用。':'口播音频已生成，请试听确认台词后采用。',started);return result;
            } catch (error) {
                if(state.status!=='cancelled' && capturedRevision===revision)
                    finish('error',Object.hasOwn(SAFE_ERRORS,error?.code)?SAFE_ERRORS[error.code]:'生成失败，请检查运行环境、凭证、台词及参考音频；未自动切换执行端或重试。',started);
                return null;
            } finally {
                clearInterval(timer);timer=null;running=null;requestId=null;emit();
            }
        })();
        return running;
    }
    function cancel() {
        if(!running || state.status!=='running') return;
        clearInterval(timer);timer=null;state.status='cancelled';state.message='已取消。';emit();
        // Keep the duplicate guard until the first request settles.
        send('/cancel',{request_id:requestId}).catch(()=>{});
    }
    function invalidate() {
        cancel();revision++;state.stale=true;state.adopted=false;state.result=null;
        if(!running)state.status='idle';state.message='参数已变化，请重新生成。';emit();
    }
    return {state,generate,cancel,invalidate,
        snapshotRestored(){state.message='工作流保留了已采用音频；执行时校验本机文件和参数，通过后直接复用，不自动重新调用 TTS。';emit();},
        get busy(){return !!running;},
        adopt(){if(state.status==='success' && state.result && !state.stale){state.adopted=true;state.message='已采用并保存本机快照；视频重试可复用，不会因语音缓存过期重新调用 TTS。';emit();return true;}return false;},
        executed(result){
            // A queued graph can finish after the user edits the panel. Only
            // acknowledge the exact preview already adopted by this panel.
            if(running || state.stale || !state.result || state.result.audio_id!==result.audio_id)return;
            state.message='工作流已复用当前音频。';emit();
        },
        destroy(){cancel();disposed=true;clearInterval(timer);revision++;}
    };
}
