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
  // crash reporter: if the dashboard script throws, show it on screen (tap to reload) and keep a copy on the receiver
  var crashSent = 0;
  function onCrash(msg, stack) {
    try {
      if (crashSent++ < 3 && URL_) fetch(URL_ + '?key=' + encodeURIComponent(KEY) + '&store=app_error', { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: JSON.stringify({ ts: new Date().toISOString(), ua: navigator.userAgent, msg: String(msg).slice(0, 500), stack: String(stack || '').slice(0, 2000) }) }).catch(function () {});
      setTimeout(function () {
        var v = document.getElementById('view'); if (v && v.innerText.trim().length > 50) return;   // page rendered anyway: stay quiet
        var d = document.getElementById('ll-crash'); if (d) return;
        d = document.createElement('div'); d.id = 'll-crash';
        d.style.cssText = 'position:fixed;left:16px;right:16px;top:40%;z-index:70;background:#1b232d;color:#eef2f6;border:1px solid #2c3642;border-radius:16px;padding:18px;font:15px/1.45 -apple-system,sans-serif;text-align:center';
        d.innerHTML = 'Le tableau de bord a rencontré une erreur.<br><small style="color:#8e9aa8">' + String(msg).replace(/</g, '&lt;').slice(0, 160) + '</small><br><button style="margin-top:12px;background:#7fe0c8;color:#0c1117;border:0;border-radius:12px;padding:10px 18px;font-weight:600">Recharger</button>';
        d.querySelector('button').onclick = function () { location.reload(); };
        document.body.appendChild(d);
      }, 2500);
    } catch (e) {}
  }
  window.addEventListener('error', function (e) { onCrash(e.message, e.error && e.error.stack); });
  window.addEventListener('unhandledrejection', function (e) { var r = e.reason || {}; if (r.code) return; onCrash('promise: ' + (r.message || r), r.stack); });
  // model ids typed on the phone can arrive capitalised or with spaces (iOS autocapitalise): normalise, fall back to defaults
  var MDEF = { quick: 'claude-haiku-5-5', default: 'claude-sonnet-5-5', complex: 'claude-opus-5-5' }, MODELS = {};
  Object.keys(MDEF).forEach(function (k) { var v = String((CFG.models || {})[k] || '').trim().toLowerCase(); MODELS[k] = /^claude-[a-z0-9.\-]+$/.test(v) ? v : MDEF[k]; });
  if (CFG.anthropicKey) CFG.anthropicKey = String(CFG.anthropicKey).trim();
  if (CFG.deepseekKey) CFG.deepseekKey = String(CFG.deepseekKey).trim();
  // AI provider: Claude by default; DeepSeek (Anthropic-compatible endpoint, same request format) when selected in settings
  var PROVIDERS = {
    claude: { name: 'Claude', url: 'https://api.anthropic.com/v1/messages', key: CFG.anthropicKey, models: MODELS },
    deepseek: { name: 'DeepSeek', url: 'https://api.deepseek.com/anthropic/v1/messages', key: CFG.deepseekKey, models: { quick: 'deepseek-flash', default: 'deepseek-flash', complex: 'deepseek-v4-pro' } }
  };
  var PROV = PROVIDERS[CFG.aiProvider === 'deepseek' ? 'deepseek' : 'claude'];
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
    st = stores[top] = { docs: {}, ready: null, timer: null, saving: null, dirty: {}, loaded: false };
    // show this device's last copy instantly, then refresh from the receiver in the background
    var cached = null; try { cached = JSON.parse(localStorage.getItem('ll_dbc_' + top) || 'null'); } catch (e) {}
    try { (JSON.parse(localStorage.getItem('ll_dirty_' + top) || '[]') || []).forEach(function (k) { st.dirty[k] = true; }); } catch (e) {}
    if (cached && typeof cached === 'object') {
      st.docs = cached;
      var fresh = load(top).then(function () { if (st.loaded) notify(top); if (Object.keys(st.dirty).length) save(top); });
      st.ready = Promise.race([fresh, new Promise(function (r) { setTimeout(r, 1200); })]);   // wait at most 1.2 s for fresh data
    } else st.ready = load(top);
    return st;
  }
  function load(top, attempt) {
    var st = stores[top]; attempt = attempt || 0;
    return fetch(rq({ action: 'state', name: 'db_' + top }), { cache: 'no-store' })
      .then(function (r) { return r.text(); })
      .then(function (t) {
        var j = {};
        try { j = JSON.parse(t); } catch (e) { throw err('unavailable', 'receiver returned non-JSON'); }
        if (j && j.ok === false && j.error !== 'missing') throw err('unavailable', 'receiver: ' + j.error);
        var missing = j && j.ok === false && j.error === 'missing';
        if (!missing && !(j && j.docs && typeof j.docs === 'object')) throw err('unavailable', 'receiver returned no collection');   // hiccup: never treat as empty
        var docs = missing ? {} : j.docs;
        st.loaded = true;
        if (st.timer || st.saving) return;   // local edits pending: keep them
        var mine = st.docs; Object.keys(st.dirty || {}).forEach(function (k) { if (mine[k] === undefined) delete docs[k]; else docs[k] = mine[k]; });   // unsent edits win
        var nMine = Object.keys(mine).length, nRemote = Object.keys(docs).length;
        if (nMine >= 5 && nRemote < nMine * 0.6) {
          // the receiver lost documents (storage glitch): keep this device's copies and write them back
          var lost = Object.keys(mine).filter(function (k) { return docs[k] === undefined; });
          lost.forEach(function (k) { docs[k] = mine[k]; st.dirty[k] = true; });
          console.warn('receiver copy of', top, 'shrank', nMine, '->', nRemote, ': restoring', lost.length);
          setTimeout(function () { save(top); }, 500);
        }
        st.docs = docs;
        try { localStorage.setItem('ll_dbc_' + top, JSON.stringify(docs)); } catch (e) {}
      })
      .catch(function (e) {
        // the receiver sometimes answers empty: retry a few times before falling back to this device's copy
        if (attempt < 3) return new Promise(function (r) { setTimeout(r, 1200 * (attempt + 1)); }).then(function () { return load(top, attempt + 1); });
        try { var c = localStorage.getItem('ll_dbc_' + top); if (c) st.docs = JSON.parse(c); } catch (x) {}
        st.offline = true;
        st.fails = (st.fails || 0) + 1;
        if (st.fails <= 6) setTimeout(function () { load(top).then(function () { if (st.loaded) notify(top); }); }, 2500 * st.fails);
      });
  }
  // Writes are read-modify-write: fetch the collection as it is on the receiver, apply only the documents
  // this device changed, then store. A device that missed the initial load (network hiccup) can never wipe others.
  function save(top, id, tries) {
    var st = stores[top];
    if (id != null) st.dirty[id] = true;
    try { localStorage.setItem('ll_dirty_' + top, JSON.stringify(Object.keys(st.dirty))); } catch (e) {}
    clearTimeout(st.timer);
    st.timer = setTimeout(function () {
      st.timer = null;
      try { localStorage.setItem('ll_dbc_' + top, JSON.stringify(st.docs)); } catch (e) {}
      var dirty = st.dirty; st.dirty = {};
      st.saving = fetch(rq({ action: 'state', name: 'db_' + top }), { cache: 'no-store' })
        .then(function (r) { return r.text(); })
        .then(function (t) {
          var j = JSON.parse(t), missing = j && j.ok === false && j.error === 'missing';
          if (!missing && !(j && j.docs && typeof j.docs === 'object')) throw new Error('no collection');
          var base = missing ? {} : j.docs;
          var known = Object.keys(st.docs).length, nb = Object.keys(base).length;
          if (known >= 5 && nb < known * 0.6) {   // receiver answered "missing"/a near-empty copy while this device knows many docs: restore, never wipe
            Object.keys(st.docs).forEach(function (k) { if (base[k] === undefined && !dirty[k]) base[k] = st.docs[k]; });
          }
          Object.keys(dirty).forEach(function (k) { if (st.docs[k] === undefined) delete base[k]; else base[k] = st.docs[k]; });
          return fetch(rq({ store: 'db_' + top }), { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: JSON.stringify({ v: 1, docs: base }) })
            .then(function (r) { return r.json(); })
            .then(function (res) {
              if (!res || !res.ok || !res.stored) throw new Error('store failed');   // {ok:true} without "stored" = the POST was not applied
              Object.keys(base).forEach(function (k) { if (!st.dirty[k]) st.docs[k] = base[k]; });
              try { if (!Object.keys(st.dirty).length) localStorage.removeItem('ll_dirty_' + top); } catch (x) {}
              st.loaded = true; notify(top);
            });
        })
        .catch(function (e) {
          console.warn('db save failed, retrying', top, e);
          Object.keys(dirty).forEach(function (k) { st.dirty[k] = true; });
          var n = (tries || 0) + 1; setTimeout(function () { save(top, null, n); }, Math.min(60000, 3000 * n));   // keep trying while the app is open
        })
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
    // like the claude.ai runtime, data() hands out a plain mutable copy (the dashboard edits loaded plans in place)
    var copy = clone(data);
    var s = freeze({ id: id, exists: true, data: function () { return clone(copy); }, metadata: META });
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
      set: function (d) { checkBody(d); var st = store(top); return st.ready.then(function () { st.docs[rest] = clone(d); save(top, rest); notify(top); }); },
      update: function (d) { checkBody(d); var st = store(top); return st.ready.then(function () { if (st.docs[rest] === undefined) throw err('invalid_argument', 'update: document does not exist'); st.docs[rest] = merge(st.docs[rest], d); save(top, rest); notify(top); }); },
      delete: function () { var st = store(top); return st.ready.then(function () { if (rest in st.docs) { delete st.docs[rest]; save(top, rest); notify(top); } }); },
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
  var inflight = 0;
  function sample(input, opts) {
    inflight++;
    return sample0(input, opts).then(function (v) { inflight--; return v; }, function (e) { inflight--; throw e; });
  }
  // "no extended thinking" is spelled differently per model: start with {type:'disabled'} and, if the API
  // answers with the right spelling for this model, remember it (per model, on this device) and retry once
  function thinkParam(model) { if (!/^claude-/.test(model)) return null; try { var v = localStorage.getItem('ll_think_' + model); if (v === 'omit') return null; if (v) return { type: v }; } catch (e) {} return { type: 'disabled' }; }
  function learnThink(model, msg) {
    var m = /"thinking":\s*\{\s*"type":\s*"([a-z_]+)"\s*\}\s*instead/i.exec(msg || '');
    try { localStorage.setItem('ll_think_' + model, m ? m[1] : 'omit'); } catch (e) {}
  }
  function sample0(input, opts) {
    opts = opts || {};
    // Manual-only coach: the dashboard's automatic analyses (recovery, sleep, strain, objective, week plan, body,
    // trends, health metrics, strength, workouts, weekly report) all call with {cache:true}; a tap on Refresh calls
    // with {cache:false}. Block the automatic ones so the AI only runs when asked. Chat, meal estimates, photos and
    // reviews never pass cache:true, so they are unaffected. Silent (no toast): the card keeps its last saved read.
    if (opts.cache === true) return Promise.reject(err('manual_only', 'Coach updates only when you tap Refresh.'));
    if (!PROV.key) return Promise.reject(err('not_granted', 'Add your ' + PROV.name + ' API key in Loop Life settings to use the AI coach.'));
    var tier = opts.modelTier && PROV.models[opts.modelTier] ? opts.modelTier : 'default';
    // an explicit claude-* model from the dashboard is honoured only on the Claude provider; DeepSeek keeps its own tiers
    var model = (opts.model && /^claude-/.test(opts.model) && PROV === PROVIDERS.claude) ? opts.model : PROV.models[tier];
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
        return fetch(PROV.url, {
          method: 'POST', signal: opts.signal,
          headers: { 'content-type': 'application/json', 'x-api-key': PROV.key, 'anthropic-version': '2023-06-01', 'anthropic-dangerous-direct-browser-access': 'true' },
          body: JSON.stringify(Object.assign({ model: model, max_tokens: opts.maxTokens || 16000, stream: true, messages: messages }, thinkParam(model) ? { thinking: thinkParam(model) } : {}))
        });
      })
      .then(function (r) {
        if (!r.ok) return r.text().then(function (t) {
          var code = r.status === 429 ? 'rate_limited' : (r.status === 401 || r.status === 403) ? 'not_granted' : r.status === 400 ? 'invalid_argument' : 'unavailable';
          var m = t; try { m = JSON.parse(t).error.message; } catch (e) {}
          if (r.status === 400 && /thinking/i.test(m) && !opts.__think) { learnThink(model, m); return sample0(input, Object.assign({}, opts, { __think: true })); }
          throw err(code, PROV.name + ' API ' + r.status + ': ' + m);
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
        if (!(e && e.code === 'aborted')) apiToast(e && e.code === 'not_granted' && /settings/.test(e.message || '') ? 'ajoute ta clé API ' + PROV.name + ' dans les réglages (bouton ⚙︎).' : String(e && e.message || e).slice(0, 220));
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
    var fx = repairJSON(a >= 0 && (c < 0 || a < c) ? t.slice(a, b + 1) : t.slice(c, d + 1));
    try { return JSON.parse(fx); } catch (e) {}
    throw err('invalid_output', 'reply was not valid JSON', t);
  }
  // models sometimes put raw line breaks or unescaped " inside strings: escape them
  // (a quote only closes a string when the next non-space char is , } ] or :)
  function repairJSON(s) {
    var o = '', inS = false;
    for (var i = 0; i < s.length; i++) {
      var ch = s[i];
      if (!inS) { o += ch; if (ch === '"') inS = true; continue; }
      if (ch === '\\') { o += ch + (s[i + 1] || ''); i++; continue; }
      if (ch === '"') {
        var j = i + 1; while (j < s.length && /\s/.test(s[j])) j++;
        if (j >= s.length || ',}]:'.indexOf(s[j]) >= 0) { o += ch; inS = false; } else o += '\\"';
        continue;
      }
      if (ch === '\n') { o += '\\n'; continue; }
      if (ch === '\r') continue;
      if (ch === '\t') { o += '\\t'; continue; }
      o += ch;
    }
    return o;
  }
  // short log of AI calls (what, how long, ok or why it failed) kept on the owner's receiver, last 20
  var logQ = [], logT = null;
  function aiLog(e) {
    return;   // disabled: diagnosis done, keeps receiver traffic low
    logQ.push(e); clearTimeout(logT);
    logT = setTimeout(function () {
      var add = logQ; logQ = [];
      fetch(rq({ action: 'state', name: 'ai_log' }), { cache: 'no-store' }).then(function (r) { return r.text(); }).then(function (t) {
        var cur = []; try { var j = JSON.parse(t); if (Array.isArray(j.items)) cur = j.items; } catch (x) {}
        return fetch(rq({ store: 'ai_log' }), { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: JSON.stringify({ items: cur.concat(add).slice(-20) }) });
      }).catch(function () {});
    }, 1500);
  }
  sample.json = function (input, opts) {
    var t0 = Date.now(), what = (typeof input === 'string' ? input : JSON.stringify(input)).slice(0, 90);
    if (!(opts && opts.__retry)) aiLog({ ts: new Date().toISOString(), what: what, ev: 'start' });
    return sampleJson(input, opts).then(function (v) { aiLog({ ts: new Date().toISOString(), what: what, ev: 'ok', ms: Date.now() - t0 }); return v; },
      function (e) { aiLog({ ts: new Date().toISOString(), what: what, ev: 'fail', ms: Date.now() - t0, code: e && e.code, msg: String(e && e.message || e).slice(0, 200) }); throw e; });
  };
  function sampleJson(input, opts) {
    return sample(input, opts).catch(function (e) {
      // dropped connection (iPhone network switch, app paused): try once more before giving up
      if (!(opts && opts.__net) && e && e.code === 'unavailable' && /load failed|failed to fetch|network/i.test(e.message || '')) return sample(input, Object.assign({}, opts || {}, { cache: false, __net: true }));
      throw e;
    }).then(function (r) {
      try { return parseJSON(r.text); }
      catch (e0) {
        if (!(opts && opts.__retry)) return sampleJson(input, Object.assign({}, opts || {}, { cache: false, __retry: true }));
        var e = e0;
        apiToast(r.truncated ? 'réponse coupée (trop longue). Réessaie.' : 'réponse illisible du modèle ' + r.modelApplied + '. Réessaie.');
        try {  // keep the failed reply on the owner's receiver for diagnosis
          var p = typeof input === 'string' ? input : JSON.stringify(input);
          fetch(rq({ store: 'ai_debug' }), { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: JSON.stringify({ ts: new Date().toISOString(), model: r.modelApplied, tier: r.modelTierApplied, truncated: r.truncated, stop: r.stop, blocks: r.blocks, outputTokens: r.outputTokens, len: r.text.length, prompt: p.slice(0, 600), promptLen: p.length, text: r.text.slice(0, 40000) }) }).catch(function () {});
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

  // New data arrived: reload only when nothing would be lost (no AI answer pending, nothing being typed, coach sheet closed)
  function busy() {
    if (inflight > 0) return true;
    var a = document.activeElement; if (a && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)) return true;
    var typed = [].some.call(document.querySelectorAll('textarea, input[type=text], input:not([type])'), function (el) { return el.value && el.value.trim().length > 0 && el.id !== 'askfile'; });
    if (typed) return true;
    var sh = document.getElementById('csheet'); if (sh && !sh.hidden) return true;
    return false;
  }
  var reloadPending = false;
  function safeReload() {
    reloadPending = true;
    (function tryNow() { if (!reloadPending) return; if (busy()) return setTimeout(tryNow, 4000); location.reload(); })();
  }
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
      var dj = JSON.parse(x[0]); if (!dj || !Array.isArray(dj.order) || !dj.order.length || !dj.days) return;   // receiver hiccup, not a dashboard
      return caches.open('ll-data-v1').then(function (c) {
        return Promise.all([c.match('/__ll/dash'), c.match('/__ll/template')]).then(function (m) {
          return Promise.all(m.map(function (r) { return r ? r.text() : ''; }));
        }).then(function (old) {
          if (old[0] === x[0] && old[1] === x[1]) return;
          var put = function (n, t) { return c.put('/__ll/' + n, new Response(t, { headers: { 'content-type': 'text/plain' } })); };
          return Promise.all([put('dash', x[0]), put('template', x[1])]).then(function () { safeReload(); });
        });
      });
    }).catch(function () {}).then(function () { clearTimeout(to); checking = false; });
  }
  setTimeout(freshCheck, 1500);
  document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'visible') freshCheck(); });
  window.addEventListener('pageshow', function () { freshCheck(); });

  /* ------------------------------------------------- push self-heal */
  // A push subscription is bound to the server's VAPID public key. If that key ever changes (or the server dropped
  // this device), every notification silently fails. Once a day, compare this device's subscription with the key
  // on the receiver and re-subscribe when they differ (permission is already granted, so this is silent).
  function b64uToBytes(s) { s = s.replace(/-/g, '+').replace(/_/g, '/'); while (s.length % 4) s += '='; var b = atob(s), a = new Uint8Array(b.length); for (var i = 0; i < b.length; i++) a[i] = b.charCodeAt(i); return a; }
  function bytesToB64u(buf) { var a = new Uint8Array(buf), s = ''; for (var i = 0; i < a.length; i++) s += String.fromCharCode(a[i]); return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); }
  function pushHeal() {
    try {
      if (!URL_ || !('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) return;
      if (Notification.permission !== 'granted') return;
      var last = +(localStorage.getItem('ll_push_chk') || 0); if (Date.now() - last < 6 * 3600 * 1000) return;
      localStorage.setItem('ll_push_chk', String(Date.now()));
    } catch (e) { return; }
    var reg, key;
    Promise.all([navigator.serviceWorker.ready, fetch(rq({ action: 'state', name: 'vapid_pub' }), { cache: 'no-store' }).then(function (r) { return r.text(); })])
      .then(function (x) {
        reg = x[0]; try { key = JSON.parse(x[1]).key; } catch (e) {}
        if (!key || !/^[A-Za-z0-9_\-]{80,}$/.test(key)) return;   // receiver hiccup or no key yet: do nothing
        return reg.pushManager.getSubscription().then(function (sub) {
          var on = false; try { on = localStorage.getItem('ll_push_on') === '1'; } catch (e) {}
          if (!sub && !on) return;   // this device never enabled notifications from the app
          var cur = sub && sub.options && sub.options.applicationServerKey ? bytesToB64u(sub.options.applicationServerKey) : null;
          return fetch(rq({ action: 'state', name: 'push_subs' }), { cache: 'no-store' }).then(function (r) { return r.text(); }).then(function (t) {
            var list = { subs: {} }; try { var p = JSON.parse(t); if (p && p.subs) list = p; else if (p && p.ok === false && p.error !== 'missing') return; } catch (e) { return; }
            var known = sub && list.subs[sub.endpoint];
            if (sub && cur === key && known && known.vapidPub === key) return;   // all good
            var old = sub ? sub.endpoint : null, keep = sub && cur === key;   // same key: only the receiver's record is missing/old
            return (sub && !keep ? sub.unsubscribe().catch(function () {}) : Promise.resolve())
              .then(function () { return keep ? sub : reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64uToBytes(key) }); })
              .then(function (ns) {
                var j = ns.toJSON();
                if (old) delete list.subs[old];
                list.subs[j.endpoint] = { endpoint: j.endpoint, keys: j.keys, vapidPub: key, added: new Date().toISOString(), ua: navigator.userAgent.slice(0, 80) };
                return fetch(rq({ store: 'push_subs' }), { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: JSON.stringify(list) });
              });
          });
        });
      }).catch(function () { try { localStorage.removeItem('ll_push_chk'); } catch (e) {} });
  }
  setTimeout(pushHeal, 4000);

  // ---- "What moved my Loop Age": exact split of the change by factor (dash.healthspan.drivers from compute.py) ----
  (function ageDrivers() {
    var LBL = { sleep_hours: ['Durée de sommeil', function (v) { return v.toFixed(1).replace('.', ',') + ' h'; }],
      sleep_consistency: ['Régularité du sommeil', function (v) { return Math.round(v) + ' %'; }],
      zones_13: ['Cardio zones 1–3', function (v) { return Math.round(v) + ' min/sem'; }],
      zones_45: ['Intensité zones 4–5', function (v) { return Math.round(v) + ' min/sem'; }],
      strength: ['Musculation', function (v) { return Math.round(v) + ' min/sem'; }],
      steps: ['Pas', function (v) { return Math.round(v).toLocaleString('fr-FR') + '/j'; }],
      vo2max: ['VO2max', function (v) { return v.toFixed(1).replace('.', ','); }],
      rhr: ['FC repos', function (v) { return Math.round(v) + ' bpm'; }],
      bmi: ['IMC', function (v) { return v.toFixed(1).replace('.', ','); }] };
    var win = 'w30'; try { win = localStorage.getItem('ll_agewin') || 'w30'; } catch (e) {}
    function hs() { try { return typeof D !== 'undefined' && D && D.healthspan && D.healthspan.drivers ? D.healthspan : null; } catch (e) { return null; } }
    function yrs(x) { return (x > 0 ? '+' : x < 0 ? '−' : '') + Math.abs(x).toFixed(1).replace('.', ',') + ' an' + (Math.abs(x) >= 2 ? 's' : ''); }
    function val(k, v) { return v == null ? '—' : (LBL[k] ? LBL[k][1](v) : String(v)); }
    function html(h) {
      var x = h.drivers[win] || h.drivers.w30 || h.drivers.w7; if (!x) return '';
      var items = x.items.filter(function (i) { return Math.abs(i.d) >= 0.05; });
      var max = Math.max.apply(null, items.map(function (i) { return Math.abs(i.d); }).concat([0.5]));
      var tabs = ['w7', 'w30'].filter(function (w) { return h.drivers[w]; }).map(function (w) {
        return '<button data-w="' + w + '" style="flex:none;padding:5px 11px;border-radius:999px;font:600 12px/1 inherit;border:1px solid var(--line,#2a333e);background:' + (w === win ? 'var(--fg,#eef2f6);color:var(--bg,#0c1117)' : 'transparent;color:var(--mute,#8e9aa8)') + '">' + (w === 'w7' ? '7 j' : '30 j') + '</button>';
      }).join('');
      var rows = items.length ? items.map(function (i) {
        var good = i.d < 0, w = Math.round(Math.abs(i.d) / max * 100), c = good ? 'var(--good,#3ecf8e)' : 'var(--bad,#ff4d5e)';
        return '<div style="padding:9px 0;border-top:1px solid var(--line,#2a333e)"><div style="display:flex;justify-content:space-between;gap:10px;align-items:baseline">' +
          '<span style="font-weight:600">' + (LBL[i.k] ? LBL[i.k][0] : i.k) + '</span><span style="font-weight:700;color:' + c + ';white-space:nowrap">' + yrs(i.d) + '</span></div>' +
          '<div style="display:flex;justify-content:space-between;gap:10px;font-size:12px;color:var(--mute,#8e9aa8);margin-top:2px"><span>' + val(i.k, i.then) + ' → ' + val(i.k, i.now) + '</span></div>' +
          '<div style="height:4px;border-radius:2px;background:var(--line,#2a333e);margin-top:6px;overflow:hidden"><div style="height:100%;width:' + w + '%;background:' + c + '"></div></div></div>';
      }).join('') : '<div style="padding:10px 0;color:var(--mute,#8e9aa8);font-size:14px;border-top:1px solid var(--line,#2a333e)">Aucun facteur n\'a bougé de façon notable sur cette période.</div>';
      var room = (h.room || []).filter(function (r) { return r.room >= 0.3; }).slice(0, 3).map(function (r) {
        return '<div style="display:flex;justify-content:space-between;gap:10px;padding:4px 0;font-size:14px"><span>' + (LBL[r.k] ? LBL[r.k][0] : r.k) + '</span><span style="color:var(--mute,#8e9aa8);white-space:nowrap">jusqu\'à −' + r.room.toFixed(1).replace('.', ',') + ' an' + (r.room >= 2 ? 's' : '') + '</span></div>';
      }).join('');
      return '<div style="display:flex;justify-content:space-between;align-items:center;gap:10px"><div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--mute,#8e9aa8)">Ce qui fait bouger ton Loop Age</div><div style="display:flex;gap:6px">' + tabs + '</div></div>' +
        '<div style="margin:8px 0 6px;font-size:15px"><b style="font-size:20px;color:' + (x.delta <= 0 ? 'var(--good,#3ecf8e)' : 'var(--bad,#ff4d5e)') + '">' + yrs(x.delta) + '</b> en ' + x.days + ' jours <span style="color:var(--mute,#8e9aa8)">(' + String(x.then).replace('.', ',') + ' → ' + String(h.age).replace('.', ',') + ')</span></div>' +
        rows + (room ? '<div style="margin-top:12px;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--mute,#8e9aa8)">Plus grande marge restante</div>' + room : '');
    }
    // the Loop Age block: shortest element whose own text names it, then its card
    function anchor(view) {
      var best = null;
      [].forEach.call(view.querySelectorAll('div,section,h1,h2,h3,h4,span,p'), function (el) {
        if (best || el.id === 'll-agedrv' || el.closest('#ll-agedrv')) return;
        var t = (el.textContent || '').trim();
        if (t.length > 40 || !/loop\s*age|âge\s*loop|healthspan/i.test(t)) return;
        var c = el;
        while (c.parentElement && c.parentElement !== view && c.offsetHeight < 110) c = c.parentElement;
        if (c !== view && c.offsetHeight >= 110 && c.offsetHeight < window.innerHeight * 1.5) best = c;
      });
      return best;
    }
    var busy = false;
    function place() {
      var h = hs(), view = document.getElementById('view'); if (!h || !view || busy) return;
      var a = anchor(view), card = document.getElementById('ll-agedrv');
      if (!a) { if (card) card.remove(); return; }
      busy = true;
      if (!card || card.previousElementSibling !== a) {
        if (card) card.remove();
        card = document.createElement('div'); card.id = 'll-agedrv';
        var cs = getComputedStyle(a);
        card.style.cssText = 'background:' + (cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)' ? cs.backgroundColor : 'var(--card,#1b232d)') + ';border-radius:' + (cs.borderRadius || '16px') + ';padding:14px 16px;margin:' + (cs.marginBottom && cs.marginBottom !== '0px' ? '0 0 ' + cs.marginBottom : '12px 0') + ';color:var(--fg,#eef2f6)';
        card.addEventListener('click', function (e) { var b = e.target.closest('button[data-w]'); if (!b) return; win = b.getAttribute('data-w'); try { localStorage.setItem('ll_agewin', win); } catch (er) {} card.innerHTML = html(hs()); });
        a.insertAdjacentElement('afterend', card);
      }
      var s = html(h); if (card._s !== s) { card.innerHTML = s; card._s = s; }
      busy = false;
    }
    var t; function soon() { clearTimeout(t); t = setTimeout(place, 120); }
    function start() { var v = document.getElementById('view'); if (!v) return setTimeout(start, 300); new MutationObserver(function () { if (!busy) soon(); }).observe(v, { childList: true, subtree: true }); soon(); }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  })();

  var CAPS = { db: DB, sample: sample, mcp: MCP };
  window.claude = freeze({ use: function (name) { return new Promise(function (res) { setTimeout(function () { res(CAPS[name] || null); }, 0); }); } });
})();
