const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app/static/app.js','utf8');
const output={value:'E:/trial-output'},calls=[],messages=[];
const ctx=vm.createContext({project:{id:'p'},busy:false,operationPending:false,localOperation:null,state:{},updateJob(){},crypto:require('node:crypto'),saving:Promise.resolve(),chosen:new Set([2,3]),
  $:()=>output,json:(method,data)=>({method,data}),localStorage:{setItem(){}},showExportInfo(){},
  message:(text,error)=>messages.push({text,error}),pickOutputFolder:async()=>false,
  api:async(path,options)=>{calls.push({path,...options});return {folder:output.value,count:1}}});
vm.runInContext(source.slice(source.indexOf('async function exportRows('),source.indexOf('\nguard(async()=>{state=')),ctx);
(async()=>{
  await ctx.exportRows(false,[7]);
  assert.equal(calls[0].path,'/projects/p/export');
  assert.deepEqual(Array.from(calls[0].data.ids),[7]);
  assert.deepEqual(Array.from(ctx.chosen),[2,3]);
  await ctx.exportRows(true);assert.deepEqual(Array.from(calls[1].data.ids),[2,3]);
  await ctx.exportRows(false);assert.equal(calls[2].data.ids,null);
  output.value='';await ctx.exportRows(false,[7]);assert.equal(calls.length,3);
  output.value='E:/trial-output';ctx.busy=true;await ctx.exportRows(false,[7]);assert.equal(calls.length,3);
  ctx.busy=false;ctx.api=async()=>{throw Error('未生成・変更あり・エラー行を生成してください')};
  await ctx.exportRows(false,[7]);assert.equal(messages.at(-1).error,true);
  assert.match(messages.at(-1).text,/未生成/);
  console.log('Row export: explicit row, selection unchanged, existing modes, cancellation, busy and errors OK');
})().catch(e=>{console.error(e);process.exitCode=1});
