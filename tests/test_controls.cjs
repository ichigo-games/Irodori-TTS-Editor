const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app/static/app.js','utf8');
const elements={},$=id=>elements[id]??={disabled:false,value:'',dataset:{}};
const input={dataset:{}},remove={dataset:{}},generate={dataset:{}},exportRow={dataset:{}},dict={dataset:{}},use={dataset:{}},name={dataset:{}},inUse={dataset:{inUse:'true'}},shared={dataset:{sharedReadOnly:'true'}};
const groups={
 '#rows input,#rows textarea,#rows select,#rows .delete-row':[input,remove],
 '#rows .generate-row,#rows .export-row':[generate,exportRow],
 '#dictionary input,#dictionary button':[dict],
 '#masterList input,#masterList button':[use,name,inUse,shared],
 '[data-shared-read-only="true"]':[shared],
};
const c=vm.createContext({$,state:{operation:null,shared_library:false},project:{id:'a',project_file:'saved.irodori'},operationPending:false,localOperation:null,busy:false,
 document:{getElementById:$,querySelectorAll:s=>groups[s]??[]}});
vm.runInContext(fs.readFileSync('app/static/shared_library.js','utf8'),c);
vm.runInContext(source.slice(source.indexOf('function controlState()'),source.indexOf('function updateJob()')),c);
$('eqPreset').value='custom';$('eqGain').value=-6;
c.applyControlState();
for(const e of [input,remove,generate,exportRow,dict,use,name])assert.equal(e.disabled,false);
assert.equal(inUse.disabled,true);assert.equal(shared.disabled,true);
c.state.operation={project:'b',kind:'generate'};c.applyControlState();
assert.equal(input.disabled,false);assert.equal(remove.disabled,false);
for(const e of [generate,exportRow,dict,use,name,$('saveSettings'),$('eqGain')])assert.equal(e.disabled,true);
c.state.operation.project='a';c.applyControlState();assert.equal(input.disabled,true);assert.equal(remove.disabled,true);
c.state.operation=null;c.operationPending=true;c.applyControlState();assert.equal(input.disabled,true);assert.equal(generate.disabled,true);
c.operationPending=false;c.state.shared_library=true;c.applyControlState();
assert.equal(input.disabled,false);assert.equal(use.disabled,false);assert.equal(dict.disabled,true);assert.equal($('registerMaster').disabled,true);assert.equal(shared.disabled,true);
assert.equal($('eqGain').disabled,false);assert.equal($('eqGain').value,-6);
$('eqPreset').value='soften';c.applyControlState();assert.equal($('eqGain').disabled,true);assert.equal($('eqGain').value,-6);
c.project={id:'unsaved'};c.applyControlState();assert.equal($('autoSaveProject').disabled,true);
console.log('Controls: own/other project, pending, shared library, used master and presets OK');
