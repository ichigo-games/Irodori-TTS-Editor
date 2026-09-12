// Keep the current media loaded when paused so resume preserves its exact position.
class PlaybackQueue {
  constructor(audio, report, onCurrent = () => {}, onState = () => {}) {
    this.audio = audio;
    this.report = report;
    this.onCurrent = onCurrent;
    this.onState = onState;
    this.items = [];
    this.index = -1;
    this.version = 0;
    this.running = false;
    audio.addEventListener('ended', () => { if (this.running) this.next(); });
    audio.addEventListener('play', () => { if (this.items.length) this.setRunning(true); });
    audio.addEventListener('pause', () => { if (!audio.ended) this.setRunning(false); });
    audio.addEventListener('error', () => {
      if (this.items.length) {
        this.stop();
        this.report('音声を再生できません。ファイルを確認してください。');
      }
    });
  }
  setRunning(value) { this.running = value; this.onState(value); }
  start(items) {
    this.stop();
    this.items = items.slice();
    this.index = -1;
    this.next();
  }
  next() {
    if (!this.items.length) return;
    this.index++;
    if (this.index >= this.items.length) {
      this.stop();
      this.report('連続再生が完了しました');
      return;
    }
    const item = this.items[this.index];
    this.audio.src = item.url;
    this.onCurrent(item.id);
    this.resume();
  }
  resume() {
    if (!this.items.length) return;
    if (this.audio.ended) { this.next(); return; }
    const item = this.items[this.index];
    const version = ++this.version;
    this.setRunning(true);
    this.report(`連続再生 ${this.index + 1} / ${this.items.length}：No.${item.id}`);
    this.audio.play().catch(() => {
      if (version === this.version) {
        this.pause();
        this.report('再生できませんでした。▶を押し直してください。');
      }
    });
  }
  pause() {
    this.version++;
    this.setRunning(false);
    this.audio.pause();
    if (this.items.length) this.report(`停止中：No.${this.items[this.index].id}（▶で続きから再生）`);
  }
  stop() {
    this.version++;
    this.items = [];
    this.index = -1;
    this.setRunning(false);
    this.audio.pause();
    this.audio.removeAttribute('src');
    this.audio.load();
    this.report('連続再生停止');
  }
}
if (typeof module !== 'undefined') module.exports = PlaybackQueue;
