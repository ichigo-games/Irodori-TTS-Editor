const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app/static/app.js','utf8');
function context(){
  const calls=[],pending=[];
  const c=vm.createContext({project:{id:'a'},state:{job:{}},busy:false,operationPending:false,localOperation:null,
    saving:Promise.resolve(),chosen:new Set([1]),crypto:require('node:crypto'),
    $:()=>({value:'E:/output'}),json:(method,data)=>({method,data}),updateJob(){},
    playback:{stop(){}},autoExportOn:()=>false,pickOutputFolder:async()=>false,
    message(){},syncProject(){},showExportInfo(){},localStorage:{setItem(){}},
    api:(path,options)=>{
      if(path.endsWith('/generate')||path.endsWith('/export')){
        calls.push({path,options});return new Promise(resolve=>pending.push(resolve));
      }
      return Promise.resolve(path==='/state'?{job:{},operation:null}:{id:'a'});
    }});
  vm.runInContext(source.slice(source.indexOf('async function startGeneration('),source.indexOf('\nfunction autoExportOn')),c);
  vm.runInContext(source.slice(source.indexOf('async function exportRows('),source.indexOf('\nguard(async()=>{state=')),c);
  return {c,calls,pending};
}
(async()=>{
  for(const first of ['generate','export']){
    const {c,calls,pending}=context();
    const task=first==='generate'?c.startGeneration('selected',[1]):c.exportRows(false,[1]);
    await c.exportRows(false,[1]);
    await assert.rejects(c.startGeneration('selected',[1]),/実行中/);
    await new Promise(r=>setImmediate(r));
    assert.equal(calls.length,1);
    assert.ok(calls[0].options.headers['X-Operation-ID']);
    assert.equal(c.operationPending,true);
    pending[0]({folder:'E:/output',count:1});await task;
    assert.equal(c.operationPending,false);
    assert.equal(c.localOperation,null);
  }
  for(const kind of ['generate','export']){
    const {c,calls}=context();let release;
    c.saving=new Promise(r=>release=r);
    const task=kind==='generate'?c.startGeneration('all',[]):c.exportRows(false,[1]);
    c.project={id:'b'};release();
    if(kind==='generate')await assert.rejects(task,/切り替わり/);else await task;
    assert.equal(calls.length,0);assert.equal(c.operationPending,false);
  }
  console.log('Submission guards: duplicate/mixed requests and project-switch races OK');
})().catch(e=>{console.error(e);process.exitCode=1});
