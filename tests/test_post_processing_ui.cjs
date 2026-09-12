const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app/static/app.js','utf8');
const elements={}; const $=id=>elements[id]??={value:'',checked:false,disabled:false,pause(){this.paused=true},removeAttribute(){this.cleared=true},load(){this.loaded=true}};
const pp={enabled:true,eq_enabled:true,eq_preset:'soften',frequency:3500,gain_db:-1.5,q:1,peak_enabled:true,peak_dbfs:-1};
let stopped=0,synced=0;
const ctx=vm.createContext({$,busy:false,state:{settings:{post_processing:pp},job:{running:false}},project:{id:'project',rows:[{id:1,generated_at:'same',pause_ms:0}]},saving:Promise.resolve(),guard:fn=>fn,json:(method,data)=>({method,data}),api:async(path,options)=>path==='/settings/post_processing'?{post_processing:options.data}:ctx.project,playback:{stop(){stopped++}},syncProject(){synced++},message(){},document:{querySelectorAll:()=>[]}});
vm.runInContext(source.slice(0,source.indexOf('const $=')),ctx);
vm.runInContext(source.slice(source.indexOf('const EQ_PRESETS'),source.indexOf("$('ppPlayBefore')")),ctx);
vm.runInContext(source.slice(source.indexOf('function updateJob()'),source.indexOf('async function startGeneration')),ctx);
(async()=>{
 ctx.renderPostProcessing();ctx.updateJob();assert.equal($('eqGain').disabled,true);
 $('eqPreset').value='custom';ctx.updateEqPresetFields();$('eqGain').value=-6;ctx.updateJob();assert.equal($('eqGain').disabled,false);assert.equal($('eqGain').value,-6);
 const row=ctx.project.rows[0],before=ctx.audioUrl('project',row),raw=ctx.audioUrl('project',row,'raw');
 await $('savePostProcessing').onclick();assert.notEqual(ctx.audioUrl('project',row),before);assert.equal(ctx.audioUrl('project',row,'raw'),raw);assert.equal(stopped,1);assert.equal(synced,1);assert.equal($('ppPreviewAudio').cleared,true);
 ctx.state.settings.post_processing={...pp,eq_preset:'soften',gain_db:-6};ctx.renderPostProcessing();assert.equal($('eqPreset').value,'custom');assert.equal($('eqGain').value,-6);
 ctx.state.job.running=true;ctx.updateJob();assert.equal($('eqGain').disabled,true);
 console.log('PP cache keys, player reset, preset polling and legacy saved values: OK');
})().catch(e=>{console.error(e);process.exitCode=1});
