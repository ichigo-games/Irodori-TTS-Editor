const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app/static/app.js','utf8');
const code=source.slice(source.indexOf('async function pollState('),source.indexOf('setInterval(guard(pollState)'));
(async()=>{
  const calls=[],synced=[];
  let fresh={job:{running:true,done:0},operation:null,shared_library:false};
  let resolveProject=null;
  const c=vm.createContext({pollBusy:false,movingRows:false,busy:true,
    project:{id:'a'},state:{job:{running:true,done:0},shared_revision:4},
    api:async path=>{calls.push(path);if(path.startsWith('/state?'))return fresh;return new Promise(r=>resolveProject=r)},
    syncSharedLibrary(){},updateJob(){c.busy=!!c.state.job.running},syncProject(p){synced.push(p)},playback:{refresh(){}}});
  vm.runInContext(code,c);
  await c.pollState();
  assert.deepEqual(calls,['/state?light=true&library_revision=4']);
  fresh={...fresh,job:{running:true,done:1}};
  const pending=c.pollState();
  await new Promise(setImmediate);
  assert.equal(calls.at(-1),'/projects/a');
  await c.pollState(); // no second request while the project fetch is pending
  assert.equal(calls.length,3);
  c.project={id:'b'};
  resolveProject({id:'a'});await pending;
  assert.equal(synced.length,0);assert.equal(c.pollBusy,false);
  fresh={...fresh,job:{running:false,done:2}};
  const completion=c.pollState();await new Promise(setImmediate);
  assert.equal(calls.at(-1),'/projects/b');
  resolveProject({id:'b'});await completion;
  assert.equal(synced.length,1);
  c.api=async()=>{throw Error('network')};
  await assert.rejects(c.pollState(),/network/);assert.equal(c.pollBusy,false);
  console.log('Polling: unchanged progress, duplicate guard, completion and project switching OK');
})().catch(e=>{console.error(e);process.exitCode=1});
