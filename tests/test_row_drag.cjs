const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const classes = {add(){}, remove(){}, toggle(){}};
const main = {inert:false};
const calls = [];
const context = vm.createContext({
  project:{id:'test',rows:[1,2,3,4,5].map(id=>({id}))},
  chosen:new Set([2,3]), busy:false, saving:Promise.resolve(), selectionAnchor:null,
  document:{querySelectorAll:()=>[],querySelector:()=>main},
  playback:{stop(){}}, updateSelection(){}, renderRows(){}, showExportInfo(){},
  message(){}, guard:fn=>fn, json:(method,data)=>({method,data}),
  api:async(path,request)=>{calls.push(request.data);return {project:{id:'test',rows:[1,2,3,4,5].map(id=>({id}))},selected:[4,5]};}
});
vm.runInContext(fs.readFileSync('app/static/row_drag.js','utf8'),context);
const row = {classList:classes,getBoundingClientRect:()=>({top:100,height:100}),closest:()=>({getBoundingClientRect:()=>({top:0,bottom:500})})};
const handle = {classList:classes};
context.setupRowDrag(row,handle,{id:5});
const sourceHandle = {classList:classes};
context.setupRowDrag({...row},sourceHandle,{id:2});
const event = {clientY:190,preventDefault(){this.prevented=true;},dataTransfer:{setData(){}}};
(async()=>{
  sourceHandle.ondragstart(event);
  assert.deepEqual([...context.chosen],[2,3]);
  await row.ondrop(event);
  assert.equal(JSON.stringify(calls),JSON.stringify([{ids:[2,3],before_id:null}]));
  assert.deepEqual([...context.chosen],[4,5]);
  assert.equal(main.inert,false);
  context.chosen=new Set([1,3]);
  const invalidHandle={classList:classes};
  context.setupRowDrag({...row},invalidHandle,{id:1});
  const invalid={...event,prevented:false};
  invalidHandle.ondragstart(invalid);
  assert.equal(invalid.prevented,true);
  context.busy=true;
  const busyEvent={...event,prevented:false};
  sourceHandle.ondragstart(busyEvent);
  assert.equal(busyEvent.prevented,true);
  console.log('Row drag: block move, selection, disjoint rejection, busy guard OK');
})().catch(e=>{console.error(e);process.exitCode=1;});
