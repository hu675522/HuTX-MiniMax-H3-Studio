// Presentation only: the existing audio elements still own URLs and playback.
export function enhanceSpeechAudio(root) {
    const cleanups=[];
    for(const audio of root.querySelectorAll('audio')){
        audio.classList.add('hutx-skinned-audio');
        const bar=document.createElement('div');bar.className='hutx-audio-player';
        const play=document.createElement('button');play.type='button';play.setAttribute('aria-label','播放音频');
        const seek=document.createElement('input');seek.type='range';seek.min=0;seek.max=1000;seek.value=0;seek.setAttribute('aria-label','音频进度');
        const time=document.createElement('span');time.className='hutx-audio-time';
        const mute=document.createElement('button');mute.type='button';mute.setAttribute('aria-label','静音');
        bar.append(play,seek,time,mute);audio.after(bar);
        const clock=value=>{const s=Math.max(0,Math.floor(value||0));return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;};
        function sync(){
            bar.hidden=audio.hidden||!audio.getAttribute('src');
            play.textContent=audio.paused?'▶':'Ⅱ';play.setAttribute('aria-label',audio.paused?'播放音频':'暂停音频');
            const duration=Number.isFinite(audio.duration)?audio.duration:0;
            time.textContent=`${clock(audio.currentTime)} / ${clock(duration)}`;
            seek.value=duration?Math.round(audio.currentTime/duration*1000):0;
            seek.disabled=!duration||!audio.seekable.length||audio.seekable.end(audio.seekable.length-1)<=0;
            seek.title=seek.disabled?'播放进度（当前音频暂不支持跳转）':'调整播放进度';
            mute.innerHTML=`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4Z"/>${audio.muted?'<path d="m16 9 5 6m0-6-5 6"/>':'<path d="M15 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>'}</svg>`;mute.title=audio.muted?'取消静音':'静音';mute.setAttribute('aria-label',mute.title);mute.setAttribute('aria-pressed',String(audio.muted));
        }
        play.onclick=async()=>{if(audio.paused){try{await audio.play();}catch{time.textContent='暂时无法播放';}}else audio.pause();};
        mute.onclick=()=>{audio.muted=!audio.muted;};
        seek.oninput=()=>{if(!seek.disabled&&Number.isFinite(audio.duration))audio.currentTime=Number(seek.value)/1000*audio.duration;};
        const events=['loadedmetadata','durationchange','progress','canplay','timeupdate','play','pause','ended','emptied','volumechange'];
        for(const event of events)audio.addEventListener(event,sync);
        const observer=new MutationObserver(sync);observer.observe(audio,{attributes:true,attributeFilter:['src','hidden']});sync();
        cleanups.push(()=>{observer.disconnect();for(const event of events)audio.removeEventListener(event,sync);bar.remove();});
    }
    return {destroy(){cleanups.forEach(fn=>fn());}};
}
