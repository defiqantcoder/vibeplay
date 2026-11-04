const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const elements = {};
const documentListeners = {};
const windowListeners = {};
const requests = [];
const opened = [];
const alerts = [];
const classes = () => {
  const set = new Set();
  return { add: x => set.add(x), remove: x => set.delete(x), contains: x => set.has(x),
    toggle: (x, on) => { if (on === undefined) on = !set.has(x); on ? set.add(x) : set.delete(x); return on; } };
};
const document = {
  activeElement: null,
  documentElement: { getAttribute: () => null },
  getElementById: id => elements[id] || null,
  querySelectorAll: () => [],
  addEventListener: (type, fn) => (documentListeners[type] ||= []).push(fn),
};
const context = { document, console, alert: msg => alerts.push(msg), confirm: () => true,
  setTimeout: () => 0, clearTimeout: () => {}, localStorage: { getItem: () => null, setItem: () => {} },
  htmx: { ajax: (...args) => requests.push(args) },
  fetch: () => Promise.resolve({ json: () => Promise.resolve({ path: '/music', cancelled: false }) }),
  HTMLDialogElement: function () {},
};
context.window = context;
context.addEventListener = (type, fn) => (windowListeners[type] ||= []).push(fn);
context.open = url => opened.push(url);
vm.createContext(context);
vm.runInContext(fs.readFileSync('src/vibeplay/templates/components/desktop_scripts.html', 'utf8'), context);
vm.runInContext(fs.readFileSync('src/vibeplay/static/app.js', 'utf8'), context);

for (const id of ['tab-library', 'tab-builder', 'nav-btn-library', 'nav-btn-builder', 'side-nav-library', 'side-nav-builder']) {
  elements[id] = { style: {}, classList: classes() };
}
context.showTab('builder');
assert(elements['side-nav-builder'].classList.contains('active'));
assert(!elements['side-nav-library'].classList.contains('active'));
assert.equal(elements['tab-builder'].style.display, 'block');

elements['cfg-mood-threshold'] = { value: '0.65' };
assert.equal(context.gatherSettingsFormPayload().mood_confidence_threshold, 0.65);
assert.equal(documentListeners.keydown?.length || 0, 0);
let calls = [];
context.triggerPlayToggle = () => calls.push('play');
context.triggerPrevTrack = () => calls.push('prev');
context.triggerNextTrack = () => calls.push('next');
const keydown = windowListeners.keydown[0];
for (const tag of ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON', 'A', 'DIV']) {
  document.activeElement = { tagName: tag, isContentEditable: tag === 'DIV', closest: () => null };
  for (const [key, code, ctrlKey] of [[' ', 'Space', false], ['ArrowLeft', 'ArrowLeft', true], ['ArrowRight', 'ArrowRight', true]]) {
    let prevented = false;
    keydown({ key, code, ctrlKey, preventDefault: () => { prevented = true; } });
    assert.equal(prevented, false, `${tag} ${key}`);
  }
}
document.activeElement = { tagName: 'BODY', isContentEditable: false, closest: () => null };
let prevented = false;
keydown({ key: ' ', code: 'Space', preventDefault: () => { prevented = true; } });
assert(prevented);
assert.deepEqual(calls, ['play']);
for (const [key, expected] of [['ArrowLeft', 'prev'], ['ArrowRight', 'next']]) {
  vm.runInContext('lastKeyTimestamp = 0', context);
  let handled = false;
  keydown({ key, code: key, ctrlKey: true, preventDefault: () => { handled = true; } });
  assert(handled);
  assert.equal(calls.at(-1), expected);
}

const listeners = {};
const row = { dataset: {}, classList: classes(), addEventListener: (type, fn) => (listeners[type] ||= []).push(fn),
  getAttribute: key => key === 'data-track-id' ? '42' : null, setAttribute: () => {} };
elements['playlist-tracks-list'] = { querySelectorAll: () => [row], getAttribute: () => '7' };
context.initPlaylistDragDrop();
context.initPlaylistDragDrop();
assert.equal(listeners.dragend.length, 1);
listeners.dragend[0]();
assert.equal(requests.length, 1);
assert.equal(requests[0][1], '/api/playlist/builder/reorder');
context.exportActivePlaylist('json');
context.exportActivePlaylist('m3u8');
assert.deepEqual(opened, ['/api/playlist/7', '/api/playlist/7/export']);
delete elements['playlist-tracks-list'];
context.exportActivePlaylist('json');
assert.equal(opened.length, 2);
assert.equal(alerts.length, 1);
elements['onboarding-folder-label'] = { textContent: 'initial' };
context.browseLibraryFolder();
setImmediate(() => {
  assert.equal(elements['onboarding-folder-label'].textContent, 'Selected: /music');
  context.fetch = () => Promise.resolve({ json: () => Promise.resolve({ path: '/ignored', cancelled: true }) });
  context.browseLibraryFolder();
  setImmediate(() => {
    assert.equal(elements['onboarding-folder-label'].textContent, 'Selected: /music');
    assert(!fs.readFileSync('src/vibeplay/templates/components/desktop_chrome.html', 'utf8').includes('triggerCacheCleanup()'));
    console.log('desktop UI behavior checks passed');
  });
});
