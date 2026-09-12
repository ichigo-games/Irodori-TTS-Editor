let rowDrag = null;
let movingRows = false;
function clearRowDrag() {
  rowDrag = null;
  document.querySelectorAll('.drop-before,.drop-after,.dragging-row').forEach(el =>
    el.classList.remove('drop-before', 'drop-after', 'dragging-row'));
}
function setupRowDrag(tr, handle, row) {
  handle.draggable = true;
  handle.classList.add('drag-handle');
  handle.title = 'ドラッグで移動 / Shiftで連続行を選択してまとめて移動';
  handle.ondragstart = e => {
    if (busy || movingRows) { e.preventDefault(); return; }
    const ids = project.rows.filter(r => chosen.has(row.id) ? chosen.has(r.id) : r.id === row.id).map(r => r.id);
    if (ids.some((id, i) => i && id !== ids[i - 1] + 1)) {
      e.preventDefault(); message('まとめて移動する行は連続して選択してください', true); return;
    }
    playback.stop();
    chosen = new Set(ids); updateSelection();
    rowDrag = {pid: project.id, ids};
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', ids.join(','));
    document.querySelectorAll('#rows tr').forEach(el => el.classList.toggle('dragging-row', chosen.has(Number(el.dataset.rowId))));
  };
  handle.ondragend = clearRowDrag;
  tr.ondragover = e => {
    if (!rowDrag || rowDrag.pid !== project.id || busy || movingRows) return;
    e.preventDefault(); e.dataTransfer.dropEffect = 'move';
    document.querySelectorAll('.drop-before,.drop-after').forEach(el => el.classList.remove('drop-before', 'drop-after'));
    const rect = tr.getBoundingClientRect();
    tr.classList.add(e.clientY < rect.top + rect.height / 2 ? 'drop-before' : 'drop-after');
    const box = tr.closest('.tablewrap');
    const bounds = box.getBoundingClientRect();
    if (e.clientY < bounds.top + 45) box.scrollTop -= 18;
    if (e.clientY > bounds.bottom - 45) box.scrollTop += 18;
  };
  tr.ondrop = guard(async e => {
    if (!rowDrag || busy || movingRows) return;
    e.preventDefault();
    const {pid, ids} = rowDrag;
    const rect = tr.getBoundingClientRect();
    const index = project.rows.findIndex(r => r.id === row.id);
    const before = e.clientY < rect.top + rect.height / 2 ? row.id : project.rows[index + 1]?.id ?? null;
    clearRowDrag();
    if (project.id !== pid || ids.includes(before)) return;
    movingRows = true;
    const main = document.querySelector('main');
    main.inert = true;
    try {
      await saving;
      const result = await api(`/projects/${pid}/move-rows`, json('POST', {ids, before_id: before}));
      project = result.project;
      chosen = new Set(result.selected);
      selectionAnchor = result.selected[0];
      renderRows(); showExportInfo();
      message(`${ids.length} 行を移動しました`);
    } finally { main.inert = false; movingRows = false; }
  });
}
