/* Loop Life PWA shim — emulates the claude.ai artifact runtime (window.claude.use) outside claude.ai.
   db     -> collections stored as blobs "db_<collection>" on the owner's own receiver
   sample -> Anthropic Messages API called from the browser with the owner's key (localStorage)
   mcp    -> the dashboard's "Sync" button: GitHub workflow_dispatch (if a token is set) + data refetch
   No secrets live in this file; everything comes from localStorage on the device. */
(function () {
  'use strict';
  var CFG = {};
  try { CFG = JSON.parse(localStorage.getItem('ll_cfg') || '{}'); } catch (e) {}
  var URL_ = CFG.receiverUrl, KEY = CFG.receiverKey;
  // model ids typed on the phone can arrive capitalised or with spaces (iOS autocapitalise): normalise, fall back to defaults
  var MDEF = { quick: 'claude-haiku-5-5', default: 'claude-sonnet-5-5', complex: 'claude-opus-5-5' }, MODELS = {};
  Object.keys(MDEF).forEach(function (k) { var v = String((CFG.models || {})[k] || '').trim().toLowerCase(); MODELS[k] = /^claude-[a-z0-9.\-]+$/.test(v) ? v : MDEF[k]; });
  if (CFG.anthropicKey) CFG.anthropicKey = String(CFG.anthropicKey).trim();
  var lastToast = 0;
  function apiToast(msg) {
    // show the real Claude API error once in a while, so a bad key / no credit / wrong model is visible
    if (Date.now() - lastToast < 20000) return; lastToast = Date.now();
    var d = document.getElementById('ll-apierr');
    if (!d) { d = document.createElement('div'); d.id = 'll-apierr'; d.style.cssText = 'position:fixed;left:12px;right:12px;top:calc(env(safe-area-inset-top,0px) + 10px);z-index:60;background:#3d2a1a;color:#ffd2a8;border:1px solid #6b4a2a;border-radius:12px;padding:10px 14px;font:14px/1.4 -apple-system,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.4)'; d.onclick = function () { d.remove(); }; (document.body || document.documentElement).appendChild(d); }
    d.textContent = 'Coach IA : ' + msg; clearTimeout(d._t); d._t = setTimeout(function () { d.remove(); }, 12000);
  }

  function rq(params) {
    var q = new URLSearchParams(Object.assign({ key: KEY }, params));
    return URL_ + (URL_.indexOf('?') < 0 ? '?' : '&') + q.toString();
  }
  function err(code, message, text) { var e = new Error(message); e.code = code; e.message = message; if (text != null) e.text = text; return e; }
  var freeze = function (o) { return Object.freeze(o); };

  /* ---------------------------------------------------------------- db */
  var SEG = /^(?!\.\.?$)[A-Za-z0-9_\-.~:@+]{1,200}$/;
  function split(path, parity, what) {
    if (typeof path !== 'string') throw new TypeError(what + ' path must be a string');
    var s = path.split('/');
    if (s.length > 16 || !s.every(function (x) { return SEG.test(x); })) throw new TypeError('bad path: ' + path);
    if (s.length % 2 !== parity) throw new TypeError(what + ' path needs an ' + (parity ? 'odd' : 'even') + ' number of segments (got ' + s.length + '): ' + path);
    return s;
  }
  var stores = {};          // top collection -> {docs:{rest:data}, loaded:Promise, dirty, timer, ver}
  var listeners = new Set(); // {kind:'doc'|'query', top, fire()}

  function store(top) {
    var st = stores[top];
    if (st) return st;
    st = stores[top] = { docs: {}, ready: null, timer: null, saving: null };
    st.ready = load(top);
    return st;
  }
  function load(top) {
    var st = stores[top];
    return fetch(rq({ action: 'state', name: 'db_' + top }), { cache: 'no-store' })
      .then(function (r) { return r.text(); })
      .then(function (t) {
        var j = {};
        try { j = JSON.parse(t); } catch (e) { throw err('unavailable', 'receiver returned non-JSON'); }
        if (j && j.ok === false && j.error !== 'missing') throw err('unavailable', 'receiver: ' + j.error);
        var docs = (j && j.docs && typeof j.docs === 'object') ? j.docs : {};
        if (st.timer || st.saving) return;   // local edits pending: keep them
        st.docs = docs;
        try { localStorage.setItem('ll_dbc_' + top, JSON.stringify(docs)); } catch (e) {}
      })
      .catch(function (e) {
        try { var c = localStorage.getItem('ll_dbc_' + top); if (c) st.docs = JSON.parse(c); } catch (x) {}
        st.offline = true;
      });
  }
  function save(top) {
    var st = stores[top];
    clearTimeout(st.timer);
    st.timer = setTimeout(function () {
      st.timer = null;
      var body = JSON.stringify({ v: 1, docs: st.docs });
      try { localStorage.setItem('ll_dbc_' + top, JSON.stringify(st.docs)); } catch (e) {}
      st.saving = fetch(rq({ store: 'db_' + top }), { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: body })
        .then(function (r) { return r.json(); })
        .then(function (j) { if (!j || !j.ok) console.warn('db save failed', top, j); })
        .catch(function (e) { console.warn('db save failed', top, e); })
        .then(function () { st.saving = null; });
    }, 600);
  }
  function clone(v) { return v == null ? v : JSON.parse(JSON.stringify(v)); }
  var META = freeze({ fromCache: false, hasPendingWrites: false });
  var snapCache = new Map();  // full path -> {json, snap}
  function docSnap(full, data) {
    var id = full.split('/').pop();
    if (data === undefined) return freeze({ id: id, exists: false, data: function () { return undefined; }, metadata: META });
    var js = JSON.stringify(data), c = snapCache.get(full);
    if (c && c.json === js) return c.snap;
    var frozen = deepFreeze(clone(data));
    var s = freeze({ id: id, exists: true, data: function () { return frozen; }, metadata: META });
    snapCache.set(full, { json: js, snap: s });
    return s;
  }
  function deepFreeze(o) { if (o && typeof o === 'object') { Object.values(o).forEach(deepFreeze); Object.freeze(o); } return o; }
  function notify(top) { listeners.forEach(function (l) { if (l.top === top) l.fire(); }); }
  function merge(a, b) {
    var out = Object.assign({}, a);
    Object.keys(b).forEach(function (k) {
      var v = b[k];
      if (v && typeof v === 'object' && v.__delete__ === true) { delete out[k]; return; }
      if (v && typeof v === 'object' && !Array.isArray(v) && out[k] && typeof out[k] === 'object' && !Array.isArray(out[k])) out[k] = merge(out[k], v);
      else out[k] = clone(v);
    });
    return out;
  }
  function checkBody(d) { if (!d || typeof d !== 'object' || Array.isArray(d)) throw err('invalid_argument', 'document body must be an object'); }
  function newId() { var a = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', s = ''; for (var i = 0; i < 20; i++) s += a[Math.floor(Math.random() * a.length)]; return s; }

  function docRef(path) {
    var s = split(path, 0, 'document'), top = s[0], rest = s.slice(1).join('/');
    var ref = {
      id: s[s.length - 1], path: path,
      get: function () { var st = store(top); return st.ready.then(function () { return docSnap(path, st.docs[rest]); }); },
      set: function (d) { checkBody(d); var st = store(top); return st.ready.then(function () { st.docs[rest] = clone(d); save(top); notify(top); }); },
      update: function (d) { checkBody(d); var st = store(top); return st.ready.then(function () { if (st.docs[rest] === undefined) throw err('invalid_argument', 'update: document does not exist'); st.docs[rest] = merge(st.docs[rest], d); save(top); notify(top); }); },
      delete: function () { var st = store(top); return st.ready.then(function () { if (rest in st.docs) { delete st.docs[rest]; save(top); notify(top); } }); },
      acquire: function () { return Promise.resolve({ acquired: true, expiresAt: new Date(Date.now() + 30000).toISOString() }); },
      onSnapshot: function (next, onErr) {
        var st = store(top), last, live = true;
        var l = { top: top, fire: function () { if (!live) return; var sn = docSnap(path, st.docs[rest]); if (sn === last) return; last = sn; try { next(sn); } catch (e) { setTimeout(function () { throw e; }); } } };
        listeners.add(l);
        st.ready.then(function () { l.fire(); });
        return function () { live = false; listeners.delete(l); };
      },
      collection: function (sub) { return collRef(path + '/' + sub); }
    };
    return freeze(ref);
  }

  function cmp(a, b) {
    if (a === b) return 0; if (a === undefined) return 1; if (b === undefined) return -1;
    if (typeof a === typeof b) return a < b ? -1 : a > b ? 1 : 0;
    return String(a) < String(b) ? -1 : 1;
  }
  var OPS = {
    '==': function (a, b) { return JSON.stringify(a) === JSON.stringify(b); }, '!=': function (a, b) { return JSON.stringify(a) !== JSON.stringify(b); },
    '<': function (a, b) { return a !== undefined && a < b; }, '<=': function (a, b) { return a !== undefined && a <= b; },
    '>': function (a, b) { return a !== undefined && a > b; }, '>=': function (a, b) { return a !== undefined && a >= b; },
    'in': function (a, b) { return (b || []).some(function (x) { return OPS['=='](a, x); }); }, 'not-in': function (a, b) { return !OPS['in'](a, b); },
    'array-contains': function (a, b) { return Array.isArray(a) && a.some(function (x) { return OPS['=='](x, b); }); }
  };
  function query(cpath, q) {
    var s = split(cpath, 1, 'collection'), top = s[0], pre = s.slice(1).join('/');
    pre = pre ? pre + '/' : '';
    function run(st) {
      var out = [];
      Object.keys(st.docs).forEach(function (k) {
        if (k.slice(0, pre.length) !== pre) return;
        var id = k.slice(pre.length); if (!id || id.indexOf('/') >= 0) return;
        var d = st.docs[k];
        if (q.where.every(function (w) { return (OPS[w[1]] || OPS['=='])(d[w[0]], w[2]); })) out.push([id, d]);
      });
      out.sort(function (a, b) { return a[0] < b[0] ? -1 : 1; });
      if (q.order) { var f = q.order[0], dir = q.order[1] === 'desc' ? -1 : 1; out.sort(function (a, b) { var r = cmp(a[1][f], b[1][f]); if (a[1][f] === undefined || b[1][f] === undefined) return r; return r * dir; }); }
      if (q.limit) out = out.slice(0, q.limit);
      return out.map(function (x) { return docSnap(cpath + '/' + x[0], x[1]); });
    }
    function qsnap(docs, prev) {
      var changes = null;
      return freeze({
        docs: docs, size: docs.length, empty: !docs.length, metadata: META,
        docChanges: function () {
          if (changes) return changes;
          var pIdx = new Map(); (prev || []).forEach(function (d, i) { pIdx.set(d.id, [i, d]); });
          var nIdx = new Map(); docs.forEach(function (d, i) { nIdx.set(d.id, i); });
          changes = [];
          (prev || []).forEach(function (d, i) { if (!nIdx.has(d.id)) changes.push({ type: 'removed', doc: d, oldIndex: i, newIndex: -1 }); });
          docs.forEach(function (d, i) { var p = pIdx.get(d.id); if (!p) changes.push({ type: 'added', doc: d, oldIndex: -1, newIndex: i }); else if (p[1] !== d || p[0] !== i) changes.push({ type: 'modified', doc: d, oldIndex: p[0], newIndex: i }); });
          return changes;
        }
      });
    }
    var self = {
      where: function (f, op, v) { return query(cpath, { where: q.where.concat([[f, op, v]]), order: q.order, limit: q.limit }); },
      orderBy: function (f, dir) { return query(cpath, { where: q.where, order: [f, dir || 'asc'], limit: q.limit }); },
      limit: function (n) { return query(cpath, { where: q.where, order: q.order, limit: n }); },
      get: function () { var st = store(top); return st.ready.then(function () { return qsnap(run(st), null); }); },
      onSnapshot: function (next) {
        var st = store(top), prev = null, live = true;
        var l = { top: top, fire: function () {
          if (!live) return; var d = run(st);
          if (prev && prev.length === d.length && prev.every(function (x, i) { return x === d[i]; })) return;
          var sn = qsnap(d, prev); prev = d;
          try { next(sn); } catch (e) { setTimeout(function () { throw e; }); }
        } };
        listeners.add(l);
        st.ready.then(function () { l.fire(); });
        return function () { live = false; listeners.delete(l); };
      }
    };
    return self;
  }
  function collRef(path) {
    split(path, 1, 'collection');
    var q = query(path, { where: [], order: null, limit: 0 });
    return freeze(Object.assign({}, q, {
      path: path,
      doc: function (id) { return docRef(path + '/' + (id == null ? newId() : id)); },
      add: function (d) { var r = docRef(path + '/' + newId()); return r.set(d).then(function () { return r; }); }
    }));
  }
  var DB = freeze({ doc: docRef, collection: collRef });

  // pull other devices' changes when the app comes back to the foreground
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState !== 'visible') return;
    Object.keys(stores).forEach(function (top) {
      var st = stores[top]; if (st.timer || st.saving) return;
      st.ready = load(top).then(function () { notify(top); });
    });
  });

  /* ------------------------------------------------------------ sample */
  var LIM = { maxPromptBytes: 262144, images: { maxCount: 5, maxInputBytes: 5 * 1024 * 1024, mediaTypes: ['image/jpeg', 'image/png', 'image/gif', 'image/webp'] } };
  var answerCache = new Map();
  function blobB64(b) {
    return new Promise(function (res, rej) { var r = new FileReader(); r.onload = function () { res(String(r.result).split(',')[1]); }; r.onerror = rej; r.readAsDataURL(b); });
  }
  function toMessages(input) {
    if (typeof input === 'string') return [{ role: 'user', content: input }];
    if (Array.isArray(input) && input.length && input[input.length - 1].role === 'user') return input.map(function (m) { return { role: m.role, content: String(m.content) }; });
    throw err('invalid_argument', 'input must be a string or a message list ending on user');
  }
  function sample(input, opts) {
    opts = opts || {};
    if (!CFG.anthropicKey) return Promise.reject(err('not_granted', 'Add your Claude API key in Loop Life settings to use the AI coach.'));
    var tier = opts.modelTier && MODELS[opts.modelTier] ? opts.modelTier : 'default';
    var model = (opts.model && /^claude-/.test(opts.model)) ? opts.model : MODELS[tier];
    var messages;
    try { messages = toMessages(input); } catch (e) { return Promise.reject(e); }
    var bytes = new Blob([JSON.stringify(messages)]).size;
    if (bytes > LIM.maxPromptBytes) return Promise.reject(err('invalid_argument', 'prompt too large'));
    var imgs = (opts.images || []).slice(0, LIM.images.maxCount);
    var ck = (opts.cache !== false && !imgs.length) ? model + '|' + JSON.stringify(messages) : null;
    if (ck && answerCache.has(ck)) { var c = answerCache.get(ck); if (Date.now() - c.t < 300000) { if (opts.onText) opts.onText({ text: c.v.text, delta: c.v.text }); return Promise.resolve(c.v); } }
    return Promise.all(imgs.map(function (b) { return blobB64(b).then(function (d) { return { type: 'image', source: { type: 'base64', media_type: b.type || 'image/jpeg', data: d } }; }); }))
      .then(function (blocks) {
        if (blocks.length) { var last = messages[messages.length - 1]; last.content = blocks.concat([{ type: 'text', text: last.content }]); }
        return fetch('https://api.anthropic.com/v1/messages', {
          method: 'POST', signal: opts.signal,
          headers: { 'content-type': 'application/json', 'x-api-key': CFG.anthropicKey, 'anthropic-version': '2023-06-01', 'anthropic-dangerous-direct-browser-access': 'true' },
          body: JSON.stringify({ model: model, max_tokens: opts.maxTokens || 16000, stream: true, thinking: { type: 'disabled' }, messages: messages })
        });
      })
      .then(function (r) {
        if (!r.ok) return r.text().then(function (t) {
          var code = r.status === 429 ? 'rate_limited' : (r.status === 401 || r.status === 403) ? 'not_granted' : r.status === 400 ? 'invalid_argument' : 'unavailable';
          var m = t; try { m = JSON.parse(t).error.message; } catch (e) {}
          throw err(code, 'Claude API ' + r.status + ': ' + m);
        });
        var reader = r.body.getReader(), dec = new TextDecoder(), buf = '', text = '', stop = null, blocks = [], outTok = null;
        function pump() {
          return reader.read().then(function (x) {
            if (x.done) return;
            buf += dec.decode(x.value, { stream: true });
            var parts = buf.split('\n\n'); buf = parts.pop();
            parts.forEach(function (ev) {
              var line = ev.split('\n').filter(function (l) { return l.indexOf('data:') === 0; }).map(function (l) { return l.slice(5).trim(); }).join('');
              if (!line) return; var j; try { j = JSON.parse(line); } catch (e) { return; }
              if (j.type === 'content_block_delta' && j.delta && j.delta.type === 'text_delta') { text += j.delta.text; if (opts.onText) try { opts.onText({ text: text, delta: j.delta.text }); } catch (e) {} }
              else if (j.type === 'message_delta' && j.delta) { stop = j.delta.stop_reason; if (j.usage) outTok = j.usage.output_tokens; }
              else if (j.type === 'content_block_start' && j.content_block) blocks.push(j.content_block.type);
              else if (j.type === 'error') throw err('unavailable', (j.error && j.error.message) || 'stream error', text);
            });
            return pump();
          });
        }
        return pump().then(function () {
          var v = { text: text, truncated: stop === 'max_tokens', modelTierApplied: tier, modelApplied: model, stop: stop, blocks: blocks, outputTokens: outTok };
          if (ck) answerCache.set(ck, { t: Date.now(), v: v });
          return v;
        });
      })
      .catch(function (e) {
        if (e && e.name === 'AbortError') throw err('aborted', 'aborted');
        if (!(e && e.code === 'aborted')) apiToast(e && e.code === 'not_granted' && /settings/.test(e.message || '') ? 'ajoute ta clé API Claude dans les réglages (bouton ⚙︎).' : String(e && e.message || e).slice(0, 220));
        if (e && e.code) throw e;
        throw err('unavailable', String(e && e.message || e));
      });
  }
  function parseJSON(t) {
    try { return JSON.parse(t); } catch (e) {}
    var m = t.match(/```(?:json)?\s*([\s\S]*?)```/); if (m) try { return JSON.parse(m[1]); } catch (e) {}
    var a = t.indexOf('{'), b = t.lastIndexOf('}'), c = t.indexOf('['), d = t.lastIndexOf(']');
    var cands = []; if (a >= 0 && b > a) cands.push([a, t.slice(a, b + 1)]); if (c >= 0 && d > c) cands.push([c, t.slice(c, d + 1)]);
    cands.sort(function (x, y) { return x[0] - y[0]; });
    for (var i = 0; i < cands.length; i++) try { return JSON.parse(cands[i][1]); } catch (e) {}
    throw err('invalid_output', 'reply was not valid JSON', t);
  }
  sample.json = function (input, opts) {
    return sample(input, opts).then(function (r) {
      try { return parseJSON(r.text); }
      catch (e) {
        apiToast(r.truncated ? 'réponse coupée (trop longue). Réessaie.' : 'réponse illisible du modèle ' + r.modelApplied + '. Réessaie.');
        try {  // keep the failed reply on the owner's receiver for diagnosis
          var p = typeof input === 'string' ? input : JSON.stringify(input);
          fetch(rq({ store: 'ai_debug' }), { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: JSON.stringify({ ts: new Date().toISOString(), model: r.modelApplied, tier: r.modelTierApplied, truncated: r.truncated, stop: r.stop, blocks: r.blocks, outputTokens: r.outputTokens, len: r.text.length, prompt: p.slice(0, 600), promptLen: p.length, head: r.text.slice(0, 1500), tail: r.text.slice(-1500) }) }).catch(function () {});
        } catch (x) {}
        throw e;
      }
    });
  };
  sample.limits = function () { return Promise.resolve(LIM); };
  Object.freeze(sample);

  /* --------------------------------------------------------------- mcp */
  // the loader starts from its cached copy and reloads itself when the receiver has newer data
  function refetchDash() { lastCheck = 0; freshCheck(); }
  function dispatch() {
    if (!CFG.ghToken || !CFG.ghRepo) return Promise.resolve(false);
    return fetch('https://api.github.com/repos/' + CFG.ghRepo + '/actions/workflows/refresh.yml/dispatches', {
      method: 'POST', headers: { Authorization: 'Bearer ' + CFG.ghToken, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' }, body: JSON.stringify({ ref: 'main' })
    }).then(function (r) { return r.status === 204; }).catch(function () { return false; });
  }
  var MCP = freeze({
    callTool: function (server, tool) {
      return dispatch().then(function (ok) {
        // the workflow takes ~1–2 min; poll the dashboard a few times, then reload
        if (ok) setTimeout(refetchDash, 120000); else setTimeout(refetchDash, 1500);
        var payload = { ok: true, dispatched: ok, note: ok ? 'Synchro lancée (GitHub Actions)' : 'Données rechargées' };
        return { ok: true, payload: payload, content: [{ type: 'text', text: JSON.stringify(payload) }], isError: false };
      });
    },
    watchTool: function () { return function () {}; },
    describeTool: function () { return Promise.reject(err('unavailable', 'not supported')); },
    listTools: function () { return Promise.resolve([]); },
    server: function () { return Promise.resolve(new Proxy({}, { get: function (_, t) { return function (i) { return MCP.callTool('', t, i).then(function (r) { return r.payload; }); }; } })); }
  });

  /* ------------------------------------------------- freshness check */
  // The loader shows the last cached copy instantly; here we fetch the receiver's copy and
  // reload when it is newer. Runs at start and every time the app comes back to the foreground.
  var checking = false, lastCheck = 0;
  function freshCheck() {
    if (checking || !window.caches || Date.now() - lastCheck < 20000) return;
    checking = true; lastCheck = Date.now();
    var ctl = new AbortController(), to = setTimeout(function () { ctl.abort(); }, 90000);
    Promise.all(['dash', 'template'].map(function (n) {
      return fetch(rq({ action: 'state', name: n }), { cache: 'no-store', signal: ctl.signal }).then(function (r) { return r.text(); });
    })).then(function (x) {
      if (x[1].indexOf('/*DATA*/') < 0) return;
      JSON.parse(x[0]);
      return caches.open('ll-data-v1').then(function (c) {
        return Promise.all([c.match('/__ll/dash'), c.match('/__ll/template')]).then(function (m) {
          return Promise.all(m.map(function (r) { return r ? r.text() : ''; }));
        }).then(function (old) {
          if (old[0] === x[0] && old[1] === x[1]) return;
          var put = function (n, t) { return c.put('/__ll/' + n, new Response(t, { headers: { 'content-type': 'text/plain' } })); };
          return Promise.all([put('dash', x[0]), put('template', x[1])]).then(function () { location.reload(); });
        });
      });
    }).catch(function () {}).then(function () { clearTimeout(to); checking = false; });
  }
  setTimeout(freshCheck, 1500);
  document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'visible') freshCheck(); });
  window.addEventListener('pageshow', function () { freshCheck(); });

  var CAPS = { db: DB, sample: sample, mcp: MCP };
  window.claude = freeze({ use: function (name) { return new Promise(function (res) { setTimeout(function () { res(CAPS[name] || null); }, 0); }); } });
})();
