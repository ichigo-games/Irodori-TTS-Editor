function applySharedReadOnly(){
  const shared=!!state?.shared_library;
  for(const id of ['sharedDictionaryNotice','sharedMasterNotice']) document.getElementById(id).hidden=!shared;
  if(shared){
    for(const id of ['addWord','saveDictionary','registerMaster','masterName','masterPath','masterFile']) document.getElementById(id).disabled=true;
    document.querySelectorAll('#dictionary input,#dictionary button').forEach(e=>e.disabled=true);
  }
  document.querySelectorAll('[data-shared-read-only="true"]').forEach(e=>e.disabled=true);
}

function syncSharedLibrary(fresh){
  if(!fresh.shared_library)return;
  state.shared_library=true;
  if(JSON.stringify(state.dictionary)!==JSON.stringify(fresh.dictionary)){
    state.dictionary=fresh.dictionary;
    renderDictionary();
  }
  if(JSON.stringify(state.settings.masters)!==JSON.stringify(fresh.settings.masters)){
    state.settings.masters=fresh.settings.masters;
    renderMasters();
    // Only replace master options; preserve row inputs, selection, and audio playback.
    document.querySelectorAll('#rows select').forEach(select=>{
      const current=select.value;
      select.replaceChildren(new Option('共通マスター',''));
      for(const m of state.settings.masters)select.add(new Option(m.name,m.id));
      if(current&&!state.settings.masters.some(m=>m.id===current))select.add(new Option('未登録のマスター',current));
      select.value=current;
    });
  }
  applySharedReadOnly();
}
