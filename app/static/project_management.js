async function refreshProjectManager() {
  const data=await api('/project-management');
  const root=$('projectManagerList');root.replaceChildren();
  for(const [area,title] of [['projects','作業プロジェクト'],['trash','ゴミ箱']]){
    root.append(node('h3',`${title}（${data[area].length}）`));
    for(const item of data[area]){
      const entry=node('div',undefined,'project-entry'), info=node('div');
      info.append(node('strong',item.name+(item.id===(project?.catalog_id??project?.id)?'（編集中）':'')),node('small',`${item.rows} 行 / 更新：${item.updated}`),node('small','ID：'+item.id));
      if(item.project_file)info.append(node('small','保存ファイル：'+item.project_file));
      const button=node('button',area==='trash'?'復元':'ゴミ箱へ移動');button.disabled=busy;
      button.onclick=guard(async()=>{
        if(busy)throw Error('生成が終わってから操作してください');
        await saving;
        if(area==='projects'&&!confirm(`「${item.name}」をゴミ箱へ移動します。あとで復元できます。`))return;
        const current=area==='projects'&&(project?.catalog_id??project?.id)===item.id;
        if(current&&!await mayLeaveProject())return;
        button.disabled=true;playback.stop();
        try{
          await api(`/projects/${item.id}/${area==='trash'?'restore':'trash'}`,json('POST',{}));
          if(current){await api(`/projects/${project.id}/close`,json('POST',{}));discardOnSwitch=null;project=null;chosen.clear();selectionAnchor=null;localStorage.removeItem('project');$('projectName').value='';$('rows').replaceChildren();$('output').value='';updateSelection();}
          state=await api('/state');renderState();updateJob();showExportInfo();
          await refreshProjectManager();
          message(area==='trash'?'復元しました。プロジェクト一覧から開けます。':'ゴミ箱へ移動しました');
        }finally{button.disabled=false;}
      });
      entry.append(info,button);root.append(entry);
    }
  }
}
$('manageProjects').onclick=guard(async()=>{await saving;await refreshProjectManager();$('projectManager').showModal();});
$('refreshProjects').onclick=guard(refreshProjectManager);
$('closeProjects').onclick=()=>$('projectManager').close();
