const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const desktop = fs.readFileSync('src/vibeplay/templates/components/desktop_scripts.html', 'utf8');
const shared = fs.readFileSync('src/vibeplay/static/app.js', 'utf8');
const base = fs.readFileSync('src/vibeplay/templates/base.html', 'utf8');
assert(!base.includes('include "components/scripts.html"'));
assert(base.includes('include "components/desktop_scripts.html"'));

function environment(includeDesktop = true) {
  const listeners = { window: {}, document: {} };
  const requests = [];
  const elements = {
    'cfg-mood-threshold': { value: '0.65' },
    'onboarding-folder-label': { textContent: '' },
  };
  const document = {
    activeElement: { tagName: 'BODY' },
    documentElement: { getAttribute: () => null },
    getElementById: id => elements[id] || null,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: (name, fn) => { (listeners.document[name] ||= []).push(fn); },
  };
  const ctx = { document, console, setTimeout, clearTimeout,
    fetch: (url, options) => {
      requests.push({ url, options });
      return Promise.resolve({ json: () => Promise.resolve(url.includes('browse-folder') ? { path: '/music/selected', cancelled: false } : {}) });
    },
    htmx: { ajax: (method, url) => requests.push({ method, url }) },
    addEventListener: (name, fn) => { (listeners.window[name] ||= []).push(fn); },
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  if (includeDesktop) vm.runInContext(desktop, ctx);
  vm.runInContext(shared, ctx);
  return { ctx, document, listeners, requests, elements };
}
function key(key, code = key, ctrlKey = false) {
  return { key, code, ctrlKey, shiftKey: false, metaKey: false, defaultPrevented: false,
    preventDefault() { this.defaultPrevented = true; } };
}
function dispatch(env, event) {
  event.target = env.document.activeElement;
  for (const listener of env.listeners.window.keydown || []) listener(event);
  for (const listener of env.listeners.document.keydown || []) listener(event);
}
(async () => {
  const e = environment();
  assert.equal(e.ctx.gatherSettingsFormPayload().mood_confidence_threshold, 0.65);
  const input = { tagName: 'INPUT', type: 'text' };
  e.document.activeElement = input;
  for (const arrow of ['ArrowLeft', 'ArrowRight']) {
    const event = key(arrow, arrow, true);
    dispatch(e, event);
    assert.equal(event.defaultPrevented, false);
    assert.equal(e.requests.length, 0);
  }
  e.document.activeElement = { tagName: 'BODY' };
  const f10 = key('F10');
  dispatch(e, f10);
  assert.equal(e.requests.filter(r => r.url === '/api/player/toggle').length, 1);

  const standalone = environment(false);
  dispatch(standalone, key('F10'));
  assert.equal(standalone.requests.filter(r => r.url === '/api/player/toggle').length, 1);

  const arrow = environment();
  dispatch(arrow, key('ArrowRight', 'ArrowRight', true));
  assert.equal(arrow.requests.filter(r => r.url === '/api/player/next').length, 1);
  const media = environment();
  media.document.activeElement = input;
  dispatch(media, key('MediaTrackPrevious'));
  assert.equal(media.requests.filter(r => r.url === '/api/player/prev').length, 1);

  e.ctx.browseLibraryFolder();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(e.elements['onboarding-folder-label'].textContent, 'Selected: /music/selected');
  e.ctx.completeOnboarding();
  const scan = e.requests.find(r => r.url === '/api/library/scan');
  assert.equal(JSON.parse(scan.options.body).path, '/music/selected');
})();
