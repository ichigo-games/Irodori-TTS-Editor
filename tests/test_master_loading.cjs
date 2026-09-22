const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app/static/app.js','utf8');
function element(){return {children:[],dataset:{},hidden:false,append(...items){this.children.push(...items)},replaceChildren(...items){this.children=items},setAttribute(){}}}
const elements={},$=id=>elements[id]??=element();
let calls=0;const requests=[];
const master={id:'one',name:'音声',reference:'voice.wav'};
const c=vm.createContext({$,state:{settings:{masters:[master]}},node:()=>element(),guard:f=>f,applyControlState(){},
 api:()=>{calls++;return new Promise(resolve=>requests.push(resolve))},message(){}});
vm.runInContext(source.slice(source.indexOf('let masterRenderVersion='),source.indexOf("$('registerMaster').onclick")),c);
(async()=>{
 $('panelSettings').hidden=true;await c.renderMasters();assert.equal(calls,0);
 $('panelSettings').hidden=false;const first=c.renderMasters();assert.equal(calls,1);
 $('panelSettings').hidden=true;
 requests.shift()([{...master,projects:[],exists:true,common:false}]);await first;
 assert.equal($('masterList').children[0].removeButton.dataset.inUse,'true');
 $('panelSettings').hidden=false;const second=c.renderMasters();
 requests.shift()([{...master,projects:[{name:'別プロジェクト',count:1}],exists:true,common:false}]);await second;
 assert.equal(calls,2);assert.equal($('masterList').children[0].removeButton.dataset.inUse,'true');
 console.log('Master loading: hidden tab skips fetch and stale response, reopen refreshes usage OK');
})().catch(e=>{console.error(e);process.exitCode=1});
