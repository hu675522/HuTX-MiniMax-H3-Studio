import fs from 'node:fs';
import assert from 'node:assert/strict';
const load=async path=>import('data:text/javascript;base64,'+Buffer.from(fs.readFileSync(path,'utf8').replace(/^import .*;\s*$/gm,'')).toString('base64'));
const {connectedSpeechSource,projectDriverMedia,driverSlotChoices,projectRoleMedia}=await load('web/js/local_driver_preview.js');
const {localMediaSpecs}=await load('web/js/local_video_input_state.js');
const audio={audio_file:'hutx-speech/adopted/'+'b'.repeat(64)+'.wav',duration_seconds:5};
const roleSources=[
 {slot:'ref_audio_1',name:'角色 A',ref:'a'},
 {slot:'ref_audio_2',name:'角色 B',ref:'b'},
 {slot:'ref_audio_3',name:'角色 C',ref:'c'}
];
const roleAudios=new Map(roleSources.map((item,index)=>[item.ref,{audio_file:`hutx-speech/adopted/${String(index+1).repeat(64)}.wav`,duration_seconds:index+1}]));
const roleBase=map=>new Map([['ref_image_1',{name:'face.png',kind:'image'}],...map]);
const projectedRoles=projectRoleMedia('all_reference',roleBase([]),roleSources,roleAudios);
assert.deepEqual(projectedRoles.slots,['ref_audio_1','ref_audio_2','ref_audio_3']);
assert.deepEqual([...projectedRoles.media.keys()],['ref_image_1','ref_audio_1','ref_audio_2','ref_audio_3']);
assert.match(projectedRoles.message,/角色 A → ref_audio_1/);
assert.equal(projectRoleMedia('text_keyframes',new Map(),roleSources,roleAudios).error,true);
const settings={family:'FL2VA',policy:'reject_conflicts',target:'auto'};
assert.deepEqual(driverSlotChoices('text_keyframes','auto',new Map()).options,[['hybrid_audio','Hybrid 音频']]);
assert.equal(driverSlotChoices('text_keyframes','auto',new Map()).selected,'hybrid_audio');
assert.deepEqual(driverSlotChoices('all_reference','auto',new Map()).options.map(([v])=>v),['ref_audio_1','ref_audio_2','ref_audio_3']);
assert.equal(driverSlotChoices('all_reference','auto',new Map([['ref_audio_1',{}]])).selected,'ref_audio_2');
assert.equal(driverSlotChoices('all_reference','auto',new Map([['ref_audio_3',{}]])).selected,'');
assert.equal(driverSlotChoices('text_keyframes','ref_audio_1',new Map()).selected,'');
const map=entries=>new Map(entries.map(([s,name])=>[s,{name,kind:s.includes('audio')?'audio':s.includes('video')?'video':'image'}]));
for(const frames of [[['first_frame','face.png']],[['first_frame','face.png'],['last_frame','last.png']]]){
 const media=map(frames),before=JSON.stringify([...media]);
 const p=projectDriverMedia('text_keyframes',media,new Map(),settings,audio);
 assert.equal(p.slot,'hybrid_audio');assert.equal(localMediaSpecs('text_keyframes',p.media).at(-1).label,'<Audio 1>');
 assert.equal(JSON.stringify([...media]),before);
 assert.equal(projectDriverMedia('text_keyframes',p.media,new Map(),settings,audio).slot,undefined);
 assert.equal(projectDriverMedia('text_keyframes',p.media,new Map(),{...settings,policy:'use_connected_audio'},audio).slot,'hybrid_audio');
}
const refs=map([['ref_image_3','face.png'],['ref_video_2','video.mp4'],['ref_audio_1','old.wav']]);
const meta=new Map([['video.mp4',{has_audio:true}]]),s={family:'Ref2VA',policy:'use_connected_audio',target:'auto'};
const p=projectDriverMedia('all_reference',refs,meta,s,audio);
const emptyPreview=projectDriverMedia('all_reference',new Map(),meta,s,audio,{preview:true});
assert.equal(emptyPreview.slot,'ref_audio_1');
assert.equal(localMediaSpecs('all_reference',emptyPreview.media,meta)[0].label,'<Audio 1>');
assert.match(emptyPreview.message,/添加参考图片或视频/);
assert.equal(projectDriverMedia('all_reference',new Map(),meta,s,audio).slot,undefined);
assert.equal(p.slot,'ref_audio_2');assert.equal(localMediaSpecs('all_reference',p.media,meta).at(-1).label,'<Audio 3>');
assert.equal(projectDriverMedia('all_reference',refs,new Map(),s,audio).slot,undefined);
assert.equal(projectDriverMedia('all_reference',refs,meta,{...s,policy:'reject_conflicts'},audio).slot,undefined);
const sparse=map([['ref_image_1','face.png'],['ref_audio_3','old.wav']]);
assert.equal(projectDriverMedia('all_reference',sparse,meta,s,audio).slot,undefined);
assert.equal(projectDriverMedia('all_reference',sparse,meta,{...s,target:'ref_audio_1'},audio).slot,undefined);
assert.equal(projectDriverMedia('all_reference',sparse,meta,{...s,target:'ref_audio_3'},audio).slot,'ref_audio_3');
assert.equal(projectDriverMedia('text_keyframes',map([['first_frame','face']]),meta,{...settings,family:'unconfirmed'},audio).slot,undefined);
assert.ok(connectedSpeechSource({}).message.includes('尚未连接'));
const source={type:'GHSpeechInputGH',id:1,widgets:[{name:'adopted_audio_file',value:'hutx-speech/adopted/'+'a'.repeat(64)+'.json'}]};
const node={inputs:[{name:'driver_audio',link:1}],graph:{links:new Map([[1,{origin_id:1,origin_slot:0}]]),getNodeById:()=>source}};
assert.equal(connectedSpeechSource(node).ref,source.widgets[0].value);
source.widgets[0].value='';assert.ok(connectedSpeechSource(node).message.includes('采用'));
source.type='AudioTrim';assert.equal(connectedSpeechSource(node).ref,undefined);
console.log('Local connected audio projection checks passed');
