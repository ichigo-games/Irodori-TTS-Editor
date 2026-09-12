const assert = require('node:assert/strict');
const Queue = require('../app/static/playback.js');
class AudioStub {
  constructor() { this.handlers = {}; this.played = []; }
  addEventListener(name, fn) { this.handlers[name] = fn; }
  play() { this.played.push(this.src); return Promise.resolve(); }
  pause() { this.paused = true; }
  load() {}
  removeAttribute() { this.src = ''; }
}
const audio = new AudioStub();
const reports = [];
const queue = new Queue(audio, text => reports.push(text));
queue.start([{id:3,url:'003.wav'},{id:7,url:'007.wav'}]);
assert.deepEqual(audio.played,['003.wav']);
audio.handlers.ended();
assert.deepEqual(audio.played,['003.wav','007.wav']);
audio.handlers.ended();
assert.match(reports.at(-1), /完了/);
queue.start([{id:1,url:'001.wav'},{id:2,url:'002.wav'}]);
queue.stop();
audio.handlers.ended();
assert.equal(audio.played.at(-1),'001.wav');
queue.start([{id:4,url:'004.wav'}]);
audio.handlers.error();
assert.equal(queue.items.length,0);
assert.match(reports.at(-1), /再生できません/);
console.log('Playback queue: order, completion, stop, error OK');

const trackedAudio = new AudioStub();
const currentRows = [], states = [];
const tracked = new Queue(trackedAudio, () => {}, id => currentRows.push(id), running => states.push(running));
tracked.start([{id:5,url:'005.wav'},{id:6,url:'006.wav'},{id:8,url:'008.wav'}]);
assert.equal(tracked.running,true);
trackedAudio.currentTime=1.25;
tracked.pause();
assert.equal(tracked.running,false);
assert.equal(trackedAudio.src,'005.wav');
assert.equal(trackedAudio.currentTime,1.25);
trackedAudio.handlers.ended();
assert.deepEqual(currentRows,[5]);
tracked.resume();
assert.equal(tracked.running,true);
assert.equal(trackedAudio.currentTime,1.25);
assert.equal(trackedAudio.played.at(-1),'005.wav');
trackedAudio.handlers.ended();
assert.deepEqual(currentRows,[5,6]);
trackedAudio.handlers.ended();
assert.deepEqual(currentRows,[5,6,8]);
trackedAudio.handlers.ended();
assert.equal(tracked.running,false);
assert.equal(tracked.items.length,0);
assert.equal(states.at(-1),false);
tracked.start([{id:9,url:'009.wav'}]);
tracked.stop();
tracked.resume();
assert.equal(tracked.running,false);
console.log('Playback toggle: pause position, resume, selection callbacks, completion and reset OK');

const liveAudio = new AudioStub();
const live = new Queue(liveAudio, () => {});
let ready = false;
live.resolve = item => item.id === 2 && !ready ? null : item;
live.start([{id:1,url:'one'},{id:2,url:'two'}]);
liveAudio.handlers.ended();
assert.equal(live.waiting,true);
assert.equal(live.running,true);
live.pause();
ready=true;
live.refresh();
assert.deepEqual(liveAudio.played,['one']);
live.resume();
assert.deepEqual(liveAudio.played,['one','two']);
assert.equal(live.waiting,false);
liveAudio.handlers.ended();
assert.equal(live.items.length,0);
ready=false;
live.start([{id:2,url:'two'}]);
live.resolve=()=>false;
live.refresh();
assert.equal(live.items.length,0);
console.log('Generation waiting, pause/resume, cancellation: OK');
