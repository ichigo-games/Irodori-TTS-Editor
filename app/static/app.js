function audioUrl(pid,row,variant='auto'){
  const pp=variant==='raw'?'raw':JSON.stringify(state?.settings?.post_processing??{});
  return `/api/projects/${pid}/audio/${row.id}?variant=${variant}&v=${encodeURIComponent(row.generated_at||'')}&pause_ms=${row.pause_ms??0}&pp=${encodeURIComponent(pp)}`;
}
const $=id=>document.getElementById(id);
let project=null, state=null, chosen=new Set(), busy=false, saving=Promise.resolve(), pollBusy=false;
const labels={pending:'未生成',generated:'生成済',generating:'生成中',error:'エラー',stale:'変更あり'};
function message(text,error=false){$('message').textContent=text;$('message').style.display='block';$('message').style.background=error?'#60313a':'#25493f';clearTimeout(message.timer);message.timer=setTimeout(()=>$('message').style.display='none',10000)}
async function api(path,options={}){const r=await fetch('/api'+path,options);if(!r.ok){const text=await r.text();let e;try{e=JSON.parse(text)}catch{throw Error(`サーバーエラー (${r.status})。起動ターミナルのログを確認してください。`)}throw Error(typeof e.detail==='string'?e.detail:JSON.stringify(e.detail))}return r.json()}
const json=(method,data)=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
function guard(fn){return async(...args)=>{try{await fn(...args)}catch(e){message(e.message,true)}}}
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e}
let selectionAnchor=null;
async function showReading(row) {
  const pid=project.id;
  await saving;
  const fresh=await api('/projects/'+pid);
  if(project?.id!==pid)return;
  const current=fresh.rows.find(r=>r.id===row.id);
  if(!current)return;
  $('readingTitle').textContent=`No.${row.id} の読み（実際のTTS送信文）`;
  $('readingText').textContent=current.preview ?? '';
  if(!$('readingDialog').open)$('readingDialog').showModal();
}
$('closeReading').onclick=()=>$('readingDialog').close();
$('readingDialog').onclick=e=>{if(e.target!==$('readingDialog'))return;const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close()};
function updateSelection(){document.querySelectorAll('#rows tr').forEach(tr=>{const selected=chosen.has(Number(tr.dataset.rowId));tr.classList.toggle('selected-row',selected);tr.setAttribute('aria-selected',String(selected))});$('bulkSelection').textContent=`${chosen.size} 行選択`;$('selection').textContent=`${chosen.size} 行選択`; $('checkAll').checked=!!project&&project.rows.length>0&&chosen.size===project.rows.length;$('checkAll').indeterminate=chosen.size>0&&chosen.size<project.rows.length}

function saveRow(row){const data={subtitle_text:row.subtitle_text,speech_text:row.speech_text,duration_scale:row.duration_scale,seed:row.seed,pause_ms:row.pause_ms??0,master_id:row.master_id??null};const pid=project.id;saving=saving.catch(()=>{}).then(()=>api(`/projects/${pid}/rows/${row.id}`,json('PUT',data)));saving.catch(e=>message('保存失敗: '+e.message,true));return saving}
function renderRows(){const body=$('rows');body.replaceChildren();if(!project)return;const fragment=document.createDocumentFragment();for(const row of project.rows){const tr=node('tr');tr.dataset.rowId=row.id;tr.tabIndex=0;const selectRow=e=>{if(e.target.closest('button,input,textarea,select,audio,a'))return;playback.stop();if(e.shiftKey&&selectionAnchor!==null){const ids=project.rows.map(r=>r.id);const a=ids.indexOf(selectionAnchor),b=ids.indexOf(row.id);if(!e.ctrlKey&&!e.metaKey)chosen.clear();for(const id of ids.slice(Math.min(a,b),Math.max(a,b)+1))chosen.add(id)}else{if(e.ctrlKey||e.metaKey){chosen.has(row.id)?chosen.delete(row.id):chosen.add(row.id)}else{if(chosen.has(row.id)){chosen.delete(row.id)}else{chosen.clear();chosen.add(row.id)}}selectionAnchor=row.id}updateSelection()};tr.onclick=selectRow;tr.onmousedown=e=>{if(e.shiftKey&&!e.target.closest('button,input,textarea,select,audio'))e.preventDefault()};tr.onkeydown=e=>{if(e.target===tr&&(e.key===' '||e.key==='Enter')){e.preventDefault();selectRow(e)}};const cells=Array.from({length:11},()=>{const td=node('td');tr.append(td);return td});cells[0].textContent='⋮';setupRowDrag(tr,cells[0],row);cells[1].textContent=String(row.id).padStart(Math.max(3,String(project.rows.length).length),'0');for(const [index,key] of [[2,'subtitle_text'],[3,'speech_text']]){const t=node('textarea');t.value=row[key];t.disabled=busy;t.setAttribute('aria-label',`${row.id} ${key==='subtitle_text'?'字幕':'読み上げ'}`);t.onchange=guard(async()=>{row[key]=t.value;const saved=await saveRow(row);Object.assign(row,saved);status.textContent=labels[row.status];status.className='status '+row.status});cells[index].append(t)}const reading=node('button','あ','icon-button');reading.title='辞書・数字補正後の読みを表示';reading.setAttribute('aria-label',`${row.id}行の実際のTTS送信文を表示`);reading.setAttribute('aria-haspopup','dialog');reading.setAttribute('aria-controls','readingDialog');reading.onclick=guard(()=>showReading(row));cells[4].append(reading);const scale=node('input');scale.type='number';scale.min='.25';scale.max='4';scale.step='.05';scale.value=row.duration_scale;scale.disabled=busy;scale.setAttribute('aria-label',`${row.id} 話速`);scale.onchange=guard(async()=>{row.duration_scale=Number(scale.value);Object.assign(row,await saveRow(row));status.textContent=labels[row.status];status.className='status '+row.status});scale.addEventListener('wheel',e=>{if(document.activeElement===scale)e.preventDefault()},{passive:false});cells[5].append(scale);const seed=node('input',undefined,'seed');seed.type='text';seed.placeholder='random';seed.value=row.seed??'';seed.disabled=busy;seed.setAttribute('aria-label',`${row.id} Seed`);seed.onchange=guard(async()=>{if(seed.value!==''&&(!/^\d+$/.test(seed.value)||Number(seed.value)>4294967295))throw Error('Seedは0〜4294967295、または空欄です');row.seed=seed.value===''?null:Number(seed.value);Object.assign(row,await saveRow(row));status.textContent=labels[row.status];status.className='status '+row.status});cells[6].append(seed,node('small','前回: '+(row.used_seed??'—')));const status=node('span',labels[row.status],'status '+row.status);cells[7].append(status);if(row.error)cells[7].append(node('small',row.error));if(row.wav){const audio=node('audio');audio.controls=true;audio.preload='none';audio.src=audioUrl(project.id,row);cells[8].append(audio)}const generate=node('button',row.wav?'再生成':'生成');generate.disabled=busy;generate.onclick=guard(()=>startGeneration('selected',[row.id]));const exportRow=node('button',undefined,'icon-button export-row');const exportIcon=node('span',undefined,'output-icon');exportIcon.setAttribute('aria-hidden','true');exportRow.append(exportIcon);exportRow.title='この行だけ出力（WAV＋字幕txt）';exportRow.setAttribute('aria-label',`${row.id}行だけ出力（WAV＋字幕txt）`);exportRow.disabled=busy;exportRow.onclick=()=>exportRows(false,[row.id]);const remove=node('button',undefined,'icon-button delete-row');const deleteIcon=node('span',undefined,'delete-icon');deleteIcon.setAttribute('aria-hidden','true');remove.append(deleteIcon);remove.title='この行を削除';remove.setAttribute('aria-label',`${row.id}行を削除`);remove.disabled=busy;remove.onclick=guard(async()=>{if(busy)return;await saving;playback.stop();await api(`/projects/${project.id}/rows/${row.id}`,{method:'DELETE'});chosen.clear();selectionAnchor=null;project=await api('/projects/'+project.id);renderRows();showExportInfo();message('行を削除しました')});cells[8].append(generate,exportRow,remove);const master=node('select');master.setAttribute('aria-label',`${row.id} マスター`);const defaultOption=node('option','共通マスター');defaultOption.value='';master.append(defaultOption);for(const item of state.settings.masters??[]){const option=node('option',item.name);option.value=item.id;master.append(option)}if(row.master_id&&!(state.settings.masters??[]).some(m=>m.id===row.master_id)){const missing=node('option','未登録のマスター');missing.value=row.master_id;master.append(missing)}master.value=row.master_id??'';master.disabled=busy;master.onchange=guard(async()=>{const previous=row.master_id;row.master_id=master.value||null;try{Object.assign(row,await saveRow(row));status.textContent=labels[row.status];status.className='status '+row.status}catch(e){row.master_id=previous;master.value=previous??'';throw e}});cells[9].append(master);const pause=node('input');pause.type='number';pause.min=0;pause.max=60000;pause.step=50;pause.value=row.pause_ms??0;pause.disabled=busy;pause.setAttribute('aria-label',`${row.id} 末尾無音ms`);pause.onchange=guard(async()=>{const value=Number(pause.value);if(!Number.isInteger(value)||value<0||value>60000)throw Error('末尾無音は0〜60000ミリ秒の整数です');const saved=await saveRow({...row,pause_ms:value});Object.assign(row,saved);playback.stop();const audio=cells[8].querySelector('audio');if(audio)audio.src=audioUrl(project.id,row)});pause.addEventListener('wheel',e=>{if(document.activeElement===pause)e.preventDefault()},{passive:false});cells[10].append(pause);fragment.append(tr)}body.append(fragment);updateSelection();renderPreviewRowOptions()}

function renderPreviewRowOptions(){
  const select=$('ppPreviewRow');const current=select.value;select.replaceChildren();
  if(!project)return;
  for(const row of project.rows.filter(r=>r.status==='generated'&&r.wav)){
    const option=node('option',`No.${row.id} ${row.subtitle_text.slice(0,20)}`);
    option.value=row.id;select.append(option);
  }
  if([...select.options].some(o=>o.value===current))select.value=current;
}

// Update only generation fields so polling never interrupts an audio player.
function syncProject(next) {
  if (!project || project.id !== next.id || project.rows.length !== next.rows.length) {
    project = next;
    renderRows();
    return;
  }
  next.rows.forEach((fresh, index) => {
    const row = project.rows[index];
    Object.assign(row, fresh);
    const cells = $('rows').children[index].cells;
    const status = cells[7].querySelector('.status');
    status.textContent = labels[row.status];
    status.className = 'status ' + row.status;
    cells[7].querySelector('small')?.remove();
    if (row.error) cells[7].append(node('small', row.error));
    cells[6].querySelector('small').textContent = '前回: ' + (row.used_seed ?? '—');
    const action = cells[8].querySelector('button');
    action.textContent = row.wav ? '再生成' : '生成';
    action.disabled = busy;
    cells[8].querySelector('.delete-row').disabled = busy;
    cells[8].querySelector('.export-row').disabled = busy;
    cells[9].querySelector('select').disabled = busy;
    cells[10].querySelector('input').disabled = busy;
    for (const cell of [cells[2], cells[3], cells[5], cells[6]]) {
      cell.querySelector('input,textarea').disabled = busy;
    }
    if (row.wav) {
      let audio = cells[8].querySelector('audio');
      const src = audioUrl(project.id,row);
      if (!audio) {
        audio = node('audio');
        audio.controls = true;
        audio.preload = 'none';
        cells[8].prepend(audio);
      }
      if (audio.getAttribute('src') !== src) audio.src = src;
    }
  });
  renderPreviewRowOptions();
}

async function loadProject(id){playback.stop();await saving;if(!id)return;project=await api('/projects/'+id);chosen.clear();selectionAnchor=null;$('projects').value=id;$('name').textContent=project.name;localStorage.setItem('project',id);renderRows();$('projectName').value=project.name;$('projectSaved').textContent=project.project_file?'保存先：'+project.project_file:project.saved_at?'保存日時：'+project.saved_at:'未保存：保存ボタンでプロジェクトを保存してください';showExportInfo();localProjectEdits=false;updateSaveStatus();if(discardOnSwitch&&discardOnSwitch!==id){const old=discardOnSwitch;discardOnSwitch=null;await api(`/projects/${old}/close`,json('POST',{}))}}
function renderDictionary(){const root=$('dictionary');root.replaceChildren();for(const entry of state.dictionary){const r=node('div',undefined,'dictrow');const enabled=node('input');enabled.type='checkbox';enabled.checked=entry.enabled;enabled.onchange=()=>entry.enabled=enabled.checked;const word=node('input');word.type='text';word.value=entry.word;word.placeholder='表記';word.oninput=()=>entry.word=word.value;const reading=node('input');reading.type='text';reading.value=entry.reading;reading.placeholder='読み';reading.oninput=()=>entry.reading=reading.value;const remove=node('button','削除');remove.onclick=()=>{state.dictionary=state.dictionary.filter(e=>e!==entry);renderDictionary()};r.append(enabled,word,node('span','→'),reading,remove);root.append(r)}applySharedReadOnly()}
function renderState(){const select=$('projects');const current=project?.id||select.value;select.replaceChildren(node('option','プロジェクトを選択'));select.firstChild.value='';for(const p of state.projects){const o=node('option',p.name);o.value=p.id;select.append(o)}if(project&&!state.projects.some(p=>p.id===project.id)){const o=node('option',project.name+'（作業中）');o.value=project.id;select.append(o)}select.value=current;$('reference').value=state.settings.reference;const common=(state.settings.masters??[]).find(m=>m.reference===state.settings.reference);$('referenceName').textContent=common?`共通マスター：${common.name}`:state.settings.reference_original_name||state.settings.reference.split(/[\\/]/).pop()||'未設定';$('referenceName').title=state.settings.reference;$('referenceDetails').textContent=`元ファイル名：${common?.original_name||state.settings.reference_original_name||'記録なし（以前の登録）'}\n保存先：${state.settings.reference||'未設定'}`;$('defaultScale').value=state.settings.duration_scale;$('defaultPause').value=state.settings.default_pause_ms??200;$('normalizeNumbers').checked=state.settings.normalize_numbers??true;$('wrapSubtitles').checked=state.settings.wrap_subtitles??true;renderPostProcessing();renderDictionary();renderMasters()}

const EQ_PRESETS={none:{frequency:3500,gain_db:0,q:1},soften:{frequency:3500,gain_db:-1.5,q:1}};
function updateEqPresetFields(){
  const preset=$('eqPreset').value;const fixed=EQ_PRESETS[preset];const custom=preset==='custom';
  for(const [id,key] of [['eqFrequency','frequency'],['eqGain','gain_db'],['eqQ','q']]){
    $(id).disabled=busy||!custom;if(fixed)$(id).value=fixed[key];
  }
}
$('eqPreset').onchange=updateEqPresetFields;
function renderPostProcessing(){
  const pp=state.settings.post_processing??{};
  $('ppEnabled').checked=pp.enabled??false;
  $('eqEnabled').checked=pp.eq_enabled??true;
  $('eqPreset').value=pp.eq_preset??'soften';
  $('eqFrequency').value=pp.frequency??3500;
  $('eqGain').value=pp.gain_db??-1.5;
  $('eqQ').value=pp.q??1;
  $('peakEnabled').checked=pp.peak_enabled??true;
  $('peakDbfs').value=pp.peak_dbfs??-1;
  // Preserve actual values from older saves that disagree with the preset label.
  const fixed=EQ_PRESETS[$('eqPreset').value];
  if(!fixed||Object.entries(fixed).some(([key,value])=>Number(pp[key]??value)!==value))$('eqPreset').value='custom';
  updateEqPresetFields();
}
$('savePostProcessing').onclick=guard(async()=>{await saving;updateEqPresetFields();state.settings=await api('/settings/post_processing',json('PUT',{
  enabled:$('ppEnabled').checked,
  eq_enabled:$('eqEnabled').checked,
  eq_preset:$('eqPreset').value,
  frequency:Number($('eqFrequency').value),
  gain_db:Number($('eqGain').value),
  q:Number($('eqQ').value),
  peak_enabled:$('peakEnabled').checked,
  peak_dbfs:Number($('peakDbfs').value),
}));playback.stop();const preview=$('ppPreviewAudio');preview.pause();preview.removeAttribute('src');preview.load();renderPostProcessing();if(project)syncProject(await api('/projects/'+project.id));message('音声補正の設定を保存しました')});
function previewAudioUrl(variant){
  const rid=Number($('ppPreviewRow').value);
  const row=project?.rows.find(r=>r.id===rid);
  if(!project||!row)throw Error('試聴する行がありません（生成済みの行を選んでください）');
  return audioUrl(project.id,row,variant);
}
$('ppPlayBefore').onclick=guard(()=>{const audio=$('ppPreviewAudio');audio.src=previewAudioUrl('raw');audio.play()});
$('ppPlayAfter').onclick=guard(()=>{const audio=$('ppPreviewAudio');audio.src=previewAudioUrl('processed');audio.play()});
function updateJob(){const j=state.job;busy=j.running;const stopping=(busy&&j.stop_requested)||(exporting&&exportStopping);$('stopGeneration').disabled=!(busy||exporting)||stopping;$('stopGeneration').textContent=stopping?'現在行の完了後に停止…':'中断';if(j.fatal_error)message('生成処理が停止しました: '+j.fatal_error,true);$('progress').max=j.total||1;$('progress').value=j.done;$('progressText').textContent=j.running?`${j.done} / ${j.total} 完了・No.${j.current??'—'} 生成中（初回はモデルをロード）${j.auto_export?`・出力 ${j.exported??0} 件`:''}`:(j.total?`${j.done} / ${j.total} 完了・エラー ${j.errors} 行${j.auto_export?`・出力 ${j.exported??0} 件`:''}`:project?`${project.rows.length} セリフ`:'台本を読み込んでください');for(const id of ['registerMaster','masterName','masterPath','masterFile','generate','applyScale','applyPause','bulkScale','bulkPause','saveSettings','defaultPause','normalizeNumbers','wrapSubtitles','savePostProcessing','ppEnabled','eqEnabled','eqPreset','eqFrequency','eqGain','eqQ','peakEnabled','peakDbfs','ppPreviewRow','ppPlayBefore','ppPlayAfter','saveDictionary','addWord','script','voice','projects','newProject','addRow','addRowAfterSelection','newRowText','export','saveProject','copyProject','projectName','chooseOutput','openProject','autoExport'])$(id).disabled=busy;document.querySelectorAll('#dictionary input,#dictionary button,#masterList button').forEach(e=>e.disabled=busy||e.dataset.inUse==='true');for(const id of ['eqFrequency','eqGain','eqQ'])$(id).disabled=busy||$('eqPreset').value!=='custom';applySharedReadOnly();announceAutoExport(j)}
let autoExportWatch=null;
let exporting=false,exportStopping=false;
function announceAutoExport(j){
  if(!autoExportWatch||j.job_id!==autoExportWatch||j.running)return;
  autoExportWatch=null;
  if(j.fatal_error)return;
  if(j.export_errors)message(`自動出力に失敗した行があります（${j.export_errors} 件）：${j.export_error}`,true);
  else if(j.exported)message(`${j.exported} 組を自動出力しました
${j.export_folder}`);
}
async function startGeneration(mode,ids){
  playback.stop();await saving;
  const auto=autoExportOn();
  // Auto-export needs a destination before the first row is generated.
  if(auto&&!$('output').value.trim()&&!await pickOutputFolder()){message('出力先が未設定のため生成を開始しませんでした。自動出力をOFFにすると出力せずに生成できます。',true);return}
  const started=await api(`/projects/${project.id}/generate`,json('POST',{mode,ids,seed_mode:$('seedMode').value,auto_export:auto,export_folder:auto?$('output').value.trim():''}));
  if(started.auto_export)autoExportWatch=started.job_id;
  state=await api('/state');updateJob();syncProject(await api('/projects/'+project.id))
}
function autoExportOn(){return $('autoExport').getAttribute('aria-checked')==='true'}
function renderAutoExport(on){$('autoExport').setAttribute('aria-checked',String(on));$('autoExport').querySelector('.switch-text').textContent=on?'ON':'OFF';try{localStorage.setItem('autoExport',on?'1':'0')}catch{}}
$('autoExport').onclick=()=>renderAutoExport(!autoExportOn());
try{renderAutoExport(localStorage.getItem('autoExport')==='1')}catch{renderAutoExport(false)}
$('projects').onchange=guard(async e=>{const next=e.target.value;if(!next)return;if(!await mayLeaveProject()){$('projects').value=project?.id??'';return;}const opened=await api(`/projects/${next}/open-saved`,json('POST',{}));await loadProject(opened.id);renderState()});
$('script').onclick=guard(async()=>{if(!await mayLeaveProject())return;await saving;const result=await api('/dialog/script',json('POST',{}));if(result.cancelled)return;state=await api('/state');await loadProject(result.id);renderState();updateJob()});
$('voice').onclick=guard(async()=>{await saving;const result=await api('/dialog/voice',json('POST',{}));if(result.cancelled)return;state.settings=result;renderState();if(project)syncProject(await api('/projects/'+project.id));message('共通マスターを保存しました')});
$('masterFile').onclick=guard(async()=>{const result=await api('/dialog/master',json('POST',{}));if(result.path)$('masterPath').value=result.path});
$('saveSettings').onclick=guard(async()=>{const pause=Number($('defaultPause').value);if($('defaultPause').value.trim()===''||!Number.isInteger(pause)||pause<0||pause>60000)throw Error('末尾無音は0〜60000ミリ秒の整数です');await saving;state.settings=await api('/settings',json('PUT',{reference:$('reference').value,duration_scale:Number($('defaultScale').value),default_pause_ms:Number($('defaultPause').value),normalize_numbers:$('normalizeNumbers').checked,wrap_subtitles:$('wrapSubtitles').checked}));renderState();if(project)syncProject(await api('/projects/'+project.id));message('設定を保存しました')});
$('addWord').onclick=()=>{state.dictionary.push({word:'',reading:'',enabled:true});renderDictionary()};
$('saveDictionary').onclick=guard(async()=>{await saving;state.dictionary=await api('/dictionary',json('PUT',state.dictionary));if(project){syncProject(await api('/projects/'+project.id))}message('辞書を保存しました')});
$('checkAll').onchange=e=>{if(!project)return;playback.stop();chosen=e.target.checked?new Set(project.rows.map(r=>r.id)):new Set();updateSelection()};
async function applyBulkValue(field, inputId, label) {
  if(busy)throw Error('生成が終わってから変更してください');
  if(!project||!chosen.size)throw Error('エディターで行を選択してください');
  const raw=$(inputId).value;
  const value=Number(raw);
  if(!raw.trim()||!Number.isFinite(value))throw Error('数値を入力してください');
  if(field==='pause_ms'&&(!Number.isInteger(value)||value<0||value>60000))throw Error('末尾無音は0〜60000ミリ秒の整数です');
  if(field==='duration_scale'&&(value<.25||value>4))throw Error('話速は0.25〜4です');
  const rows=project.rows.filter(r=>chosen.has(r.id));
  const main=document.querySelector('main');
  main.inert=true;
  playback.stop();
  try {
    await saving;
    for(const row of rows)Object.assign(row,await saveRow({...row,[field]:value}));
    message(`${rows.length} 行に${label}を適用しました`);
  } finally {
    main.inert=false;
    renderRows();
    showExportInfo();
  }
}
$('applyScale').onclick=guard(()=>applyBulkValue('duration_scale','bulkScale','話速'));
$('applyPause').onclick=guard(()=>applyBulkValue('pause_ms','bulkPause','末尾無音'));

$('generate').onclick=guard(async()=>{if(!project)throw Error('台本を読み込んでください');if(busy)return;const target=await chooseTarget('生成する行を選んでください','すべて生成','選択行を生成','（すべて生成は生成済み以外が対象）');if(target)await startGeneration(target==='selected'?'selected':'missing',[...chosen])});
// Keep the destination and export result visible, including after a reload.
const exportInfo = node('div');
exportInfo.id = 'exportInfo';
exportInfo.setAttribute('role', 'status');

document.querySelector('.export').after(exportInfo);
let exportError = '';
let exportProject = null;
function showExportInfo() {
  if (!project) { exportInfo.textContent = ''; exportInfo.hidden = true; return; }
  if (exportProject !== project.id) {
    exportProject = project.id;
    exportError = '';
    $('output').value = project.output_folder ?? localStorage.getItem('output:' + project.id) ?? '';
  }
  const pending = project.rows.filter(r => r.status !== 'generated');
  const last = project.last_export || localStorage.getItem('export:' + project.id);
  const lines = [];


  if (exportError) lines.push('書き出し失敗：' + exportError);
  exportInfo.textContent = lines.join('\n');
  exportInfo.hidden = !lines.length;
}
function renderOutputFolder() {
  $('outputFolder').textContent = '出力先：' + ($('output').value.trim() || '未設定（出力時に選択します）');
}
{
  const valueProperty = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
  Object.defineProperty($('output'), 'value', {
    configurable: true,
    get() { return valueProperty.get.call(this); },
    set(v) { valueProperty.set.call(this, v); renderOutputFolder(); }
  });
  renderOutputFolder();
}
$('output').addEventListener('input', () => {
  if (project) localStorage.setItem('output:' + project.id, $('output').value);
});
async function exportRows(selectedOnly, explicitIds = null) {
  try {
    if (!project) throw Error('台本を読み込んでください');
    if (busy) throw Error('生成中です。完了後に出力してください');
    const pid = project.id;
    const exportingProject = project;
    const ids = explicitIds ? [...explicitIds] : selectedOnly ? [...chosen] : null;
    await saving;
    if (project?.id !== pid) throw Error('プロジェクトが切り替わりました。もう一度出力してください');
    if (selectedOnly && !ids.length) throw Error('出力する行を選択してください');
    if (!$('output').value.trim() && !await pickOutputFolder()) return;
    if (project?.id !== pid) throw Error('プロジェクトが切り替わりました。もう一度出力してください');
    localStorage.setItem('output:' + project.id, $('output').value);
    exporting = true; exportStopping = false; updateJob();
    let result;
    try {
      result = await api(`/projects/${project.id}/export`, json('POST', {folder: $('output').value, ids}));
    } finally { exporting = false; exportStopping = false; updateJob(); }
    localStorage.setItem('export:' + pid, result.folder);exportingProject.last_export=result.folder;exportingProject.output_folder=result.folder;
    exportError = '';
    showExportInfo();
    message(result.stopped ? `中断しました：${result.count} 組を出力済み\n${result.folder}` : `${result.count} 組を出力しました\n${result.folder}`);
  } catch (e) {
    exportError = e.message;
    showExportInfo();
    message(e.message, true);
  }
};
setInterval(showExportInfo, 1000);
guard(async()=>{state=await api('/state');renderState();const last=localStorage.getItem('project');if(state.projects.some(p=>p.id===last)){const opened=await api(`/projects/${last}/open-saved`,json('POST',{}));await loadProject(opened.id);renderState();}updateJob()})();
setInterval(guard(async()=>{if(pollBusy||movingRows)return;pollBusy=true;try{const wasBusy=busy;const fresh=await api('/state');if(movingRows)return;state.job=fresh.job;syncSharedLibrary(fresh);updateJob();if(project&&(busy||wasBusy)){syncProject(await api('/projects/'+project.id));playback.refresh()}}finally{pollBusy=false}}),1800);

async function persistProject(copyProject) {
  if (!project) throw Error('台本を読み込んでください');
  await saving;
  const result = await api(`/projects/${project.id}/save`, json('POST', {
    name: $('projectName').value, output_folder: $('output').value, copy_project: false, native_dialog: copyProject || !project.project_file
  }));
  if (result.cancelled) return false;
  state = await api('/state');
  await loadProject(result.project.id);
  renderState();
  $('projectSaved').textContent = '保存済み：' + result.path;
  message('プロジェクトを保存しました');
  return true;
}
$('saveProject').onclick = guard(() => persistProject(false));
$('copyProject').onclick = guard(() => persistProject(true));

async function pickOutputFolder() {
  const result = await api('/dialog/output', json('POST', {folder: $('output').value.trim()}));
  if (!result.path) return false;
  $('output').value = result.path;
  if (project) localStorage.setItem('output:' + project.id, result.path);
  return true;
}
$('chooseOutput').onclick = guard(pickOutputFolder);

$('openProject').onclick = guard(async () => {
  if(!await mayLeaveProject())return;
  await saving;
  const result = await api('/projects/open-file', {method:'POST'});
  if (result.cancelled) return;
  state = await api('/state');
  await loadProject(result.project.id);
  renderState();
  message('プロジェクトを開きました');
});

function chooseTarget(title, allLabel, selectedLabel, allNote = '') {
  const dialog = $('exportChoice'), count = chosen.size;
  $('exportChoiceTitle').textContent = title;
  $('exportAll').textContent = allLabel;
  $('exportSelected').textContent = selectedLabel;
  $('exportChoiceInfo').textContent = `全 ${project.rows.length} 行／選択中 ${count} 行${allNote}`;
  $('exportSelected').disabled = !count;
  return new Promise(resolve => {
    const finish = value => { dialog.close(); resolve(value); };
    $('exportAll').onclick = () => finish('all');
    $('exportSelected').onclick = () => finish('selected');
    $('exportCancel').onclick = () => finish(null);
    dialog.oncancel = () => resolve(null);
    dialog.showModal();
  });
}
$('export').onclick = guard(async () => {
  if (!project) throw Error('台本を読み込んでください');
  if (busy) throw Error('生成中です。完了後に出力してください');
  const target = await chooseTarget('出力する行を選んでください', '全件を出力', '選択行のみ出力');
  if (target) await exportRows(target === 'selected');
});
const playback = new PlaybackQueue($('continuousAudio'),
  text => $('playbackStatus').textContent = text,
  id => {
    chosen=new Set([id]);selectionAnchor=id;updateSelection();
    document.querySelector(`#rows tr[data-row-id="${id}"]`)?.scrollIntoView({block:'nearest'});
  },
  running => {
    $('togglePlayback').textContent=running?'■':'▶';
    $('togglePlayback').setAttribute('aria-label',running?'連続再生を停止（位置を保持）':'連続再生／続きから再生');
    $('togglePlayback').title=running?'停止（再生位置を保持）':'選択行から再生／停止位置から再開';
  });
playback.resolve = item => {
  const row=project?.rows.find(r=>r.id===item.id);
  if(!row)return false;
  const job=state.job;
  if(job.running&&job.project===project.id&&job.ids?.includes(row.id)&&!job.completed_ids?.includes(row.id))return null;
  return row.status==='generated'&&row.wav?{id:row.id,url:audioUrl(project.id,row)}:false;
};
$('stopGeneration').onclick=guard(async()=>{
  if(!project)return;
  if(exporting)exportStopping=true;
  updateJob();
  const reply=await api(`/projects/${project.id}/stop-generation`,json('POST',{}));
  if('running' in reply)state.job=reply;
  updateJob();
  message('現在の行が完了したら停止します');
});
async function togglePlayback() {
  await saving;
  if(playback.running){playback.pause();return;}
  if(playback.items.length){playback.resume();return;}
  if(!project)throw Error('台本を読み込んでください');
  const selectedIndex=project.rows.findIndex(r=>chosen.has(r.id));
  const rows=project.rows.slice(Math.max(0,selectedIndex)).filter(r=>(r.status==='generated'&&r.wav)||(busy&&state.job.project===project.id&&state.job.ids?.includes(r.id)));
  if(!rows.length)throw Error('開始行以降に生成済みの音声がありません');
  document.querySelectorAll('audio').forEach(audio=>audio.pause());
  playback.start(rows.map(r=>({id:r.id,url:audioUrl(project.id,r)})));
}
$('togglePlayback').onclick=guard(togglePlayback);
document.addEventListener('play', event => {
  if (event.target instanceof HTMLAudioElement && event.target !== $('continuousAudio')) playback.stop();
}, true);

async function createEmptyProject() {
  if(!await mayLeaveProject())return;
  await saving;
  playback.stop();
  const created = await api('/projects/new', {method:'POST'});
  state = await api('/state');
  await loadProject(created.id);
  renderState();
  $('newRowText').focus();
}
$('newProject').onclick = guard(createEmptyProject);
let addingRow = false;
async function addRows(beforeId) {
  if (addingRow || busy) return;
  const text = $('newRowText').value;
  if (!text.trim()) throw Error('追加するセリフを入力してください');
  addingRow = true;
  try {
    await saving;
    if (!project) await createEmptyProject();
    const added = await api(`/projects/${project.id}/rows`, json('POST', {text, before_id: beforeId}));
    project = await api('/projects/' + project.id);
    renderRows();
    $('newRowText').value = '';
    $('newRowText').focus();
    const first = added.ids[0], last = added.ids[added.ids.length - 1];
    document.querySelector(`#rows tr[data-row-id="${first}"]`)?.scrollIntoView({block:'nearest'});
    message(added.ids.length > 1
      ? `No.${first}〜No.${last} を${added.ids.length}行追加しました。字幕と読み上げは行内で個別に編集できます。`
      : `No.${first} を追加しました。字幕と読み上げは行内で個別に編集できます。`);
    return added.ids;
  } finally { addingRow = false; }
}
$('addRow').onclick = guard(() => addRows(null));
$('addRowAfterSelection').onclick = guard(async () => {
  if (!project) throw Error('台本を読み込んでください');
  if (!chosen.size) throw Error('挿入する位置の行を選択してください');
  const ids = project.rows.map(r => r.id);
  const lastSelectedIndex = Math.max(...ids.map((id, i) => chosen.has(id) ? i : -1));
  const beforeId = lastSelectedIndex + 1 < ids.length ? ids[lastSelectedIndex + 1] : null;
  const addedIds = await addRows(beforeId);
  if (addedIds) {
    // Select the row just added so repeated clicks keep chaining downward.
    const newLast = addedIds[addedIds.length - 1];
    chosen = new Set([newLast]);
    selectionAnchor = newLast;
    updateSelection();
  }
});
$('newRowText').addEventListener('keydown', event => {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    $('addRow').click();
  }
});

const workTabs = Array.from(document.querySelectorAll('[role="tab"]'));
function activateTab(tab) {
  for (const item of workTabs) {
    const active = item === tab;
    item.setAttribute('aria-selected', String(active));
    item.tabIndex = active ? 0 : -1;
    $(item.dataset.panel).hidden = !active;
  }
}
workTabs.forEach((tab, index) => {
  tab.onclick = () => activateTab(tab);
  tab.onkeydown = event => {
    const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End'];
    if (!keys.includes(event.key)) return;
    event.preventDefault();
    let next = event.key === 'Home' ? 0 : event.key === 'End' ? workTabs.length - 1 :
      (index + (event.key === 'ArrowRight' ? 1 : -1) + workTabs.length) % workTabs.length;
    activateTab(workTabs[next]);
    workTabs[next].focus();
  };
});


let masterRenderVersion=0;
async function renderMasters(){
  const version=++masterRenderVersion;
  const root=$('masterList');root.replaceChildren();
  for(const master of state.settings.masters??[]){
    const entry=node('div',undefined,'master-entry');
    const info=node('div');info.append(node('strong',master.name),node('small',`元ファイル名：${master.original_name||'記録なし（以前の登録）'}`),node('small','保存先：'+master.reference));const usage=node('small','使用状況を確認中…');info.append(usage);entry.append(info);entry.dataset.masterId=master.id;
    const use=node('button','共通マスターに設定');use.disabled=busy;
    use.onclick=guard(async()=>{
      await saving;
      state.settings=await api('/settings',json('PUT',{...state.settings,reference:master.reference}));
      renderState();if(project)syncProject(await api('/projects/'+project.id));
      message(`${master.name} を共通マスターに設定しました`);
    });
    const name=node('input');name.value=master.name;name.maxLength=100;name.setAttribute('aria-label',master.name+' の登録名');
    const rename=node('button','名前を変更');rename.disabled=busy;
    rename.onclick=guard(async()=>{await saving;state.settings=await api('/masters/'+master.id,json('PUT',{name:name.value}));renderState();if(project)renderRows()});
    const remove=node('button','登録を削除');remove.dataset.inUse='true';remove.disabled=true;
    remove.onclick=guard(async()=>{await saving;state.settings=await api('/masters/'+master.id,{method:'DELETE'});renderState();if(project)renderRows();message('マスター登録を削除しました。WAVファイルは保存先に残しています。')});
    if(master.shared){info.append(node('small','通常版から参照（読み取り専用）'));for(const control of [name,rename,remove]){control.dataset.sharedReadOnly='true';control.disabled=true}}
    entry.append(use,name,rename,remove);root.append(entry);
    entry.usageLabel=usage;entry.removeButton=remove;
  }
  if(!root.children.length)root.append(node('p','登録済みマスターはありません。'));
  try {
    const masters=await api('/masters');if(version!==masterRenderVersion)return;
    for(const entry of root.children){const m=masters.find(m=>m.id===entry.dataset.masterId);if(!m)continue;
      entry.usageLabel.textContent=[m.common?'共通マスターとして使用中':'',...m.projects.map(p=>`${p.name}：${p.count} 行で使用`),m.exists?'':'音声ファイルが見つかりません'].filter(Boolean).join(' / ')||'未使用';
      entry.removeButton.dataset.inUse=String(m.common||m.projects.length>0);
      entry.removeButton.disabled=busy||m.common||m.projects.length>0||!!m.shared;
    }
  }catch(e){if(version===masterRenderVersion)message(e.message,true)}
}
$('registerMaster').onclick=guard(async()=>{
  await saving;
  const name=$('masterName').value.trim();
  if(!name)throw Error('マスター名を入力してください');
  const file=null;
  if(file){const data=new FormData();data.append('name',name);data.append('file',file);state.settings=await api('/masters/upload',{method:'POST',body:data})}
  else{const reference=$('masterPath').value.trim()||state.settings.reference;if(!reference)throw Error('WAVファイルか絶対パスを指定してください');state.settings=await api('/masters',json('POST',{name,reference}))}
  $('masterName').value='';$('masterPath').value='';$('masterFile').value='';
  renderState();if(project)renderRows();message('マスターを登録しました');
});

let discardOnSwitch=null;
let localProjectEdits=false;
function updateSaveStatus(){
  if(!project)return;
  $('projectSaved').textContent=(project.dirty?'● 未保存の変更あり':'保存済み')+(project.project_file?'：'+project.project_file:'：名前を付けて保存してください');
  $('autoSaveProject').disabled=busy||!project.project_file;
  $('autoSaveProject').checked=project.autosave??false;
}
async function mayLeaveProject(){
  if(!project)return true;
  await saving;
  const fresh=await api('/projects/'+project.id);
  project.dirty=fresh.dirty||localProjectEdits;
  if(project.dirty){
    if(confirm('未保存の変更があります。保存してから切り替えますか？')){
      if(!await persistProject(false))return false;
    }else if(!confirm('未保存の変更を破棄して切り替えますか？'))return false;
  }
  discardOnSwitch=project.id;
  return true;
}
$('autoSaveProject').onchange=guard(async()=>{
  if(!project)return;
  await saving;
  const fresh=await api(`/projects/${project.id}/autosave`,json('PUT',{enabled:$('autoSaveProject').checked}));
  Object.assign(project,{autosave:fresh.autosave,dirty:fresh.dirty});updateSaveStatus();
});
window.addEventListener('beforeunload',e=>{if(project&&(project.dirty||busy)){e.preventDefault();e.returnValue='';}});
document.querySelector('main').addEventListener('input',e=>{if(project&&(e.target.closest('#rows')||['projectName','output','newRowText'].includes(e.target.id))){localProjectEdits=true;project.dirty=true;updateSaveStatus();}});
let saveStatusPolling=false;
setInterval(guard(async()=>{
  if(!project||busy||movingRows||saveStatusPolling||document.activeElement?.matches('input,textarea'))return;
  saveStatusPolling=true;
  try{
    await saving;const pid=project.id;
    const fresh=await api('/projects/'+pid);
    if(project?.id!==pid)return;
    project.dirty=fresh.dirty||localProjectEdits;project.autosave=fresh.autosave;updateSaveStatus();
    if(project.autosave&&project.dirty)await persistProject(false);
  }finally{saveStatusPolling=false;}
}),3000);
