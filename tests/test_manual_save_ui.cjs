const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app/static/app.js','utf8');
const ctx=vm.createContext({project:{id:'a'},saving:Promise.resolve(),api:async()=>({dirty:true}),localProjectEdits:false,discardOnSwitch:null,confirm:()=>false,persistProject:async()=>false});
vm.runInContext(source.slice(source.indexOf('async function mayLeaveProject'),source.indexOf("$('autoSaveProject').onchange")),ctx);
(async()=>{assert.equal(await ctx.mayLeaveProject(),false);assert.equal(ctx.discardOnSwitch,null);ctx.confirm=()=>true;assert.equal(await ctx.mayLeaveProject(),false);ctx.persistProject=async()=>true;assert.equal(await ctx.mayLeaveProject(),true);assert.equal(ctx.discardOnSwitch,'a');console.log('Unsaved switch cancellation and save confirmation OK')})().catch(e=>{console.error(e);process.exitCode=1});
