// Loop Life — home-screen widget for the Scriptable app (iPhone), medium size.
// Four dials like the app's Home: Sleep, Recovery, Strain, Nutrition, each with its name and a detail line.
// Tapping the widget opens Loop Life.
// Setup: paste into a new Scriptable script, fill RECEIVER and KEY (same values as in the Loop Life app settings),
// then add a MEDIUM Scriptable widget on the Home Screen and choose this script.
// The values stay on your phone; this repo is public, so never commit them filled in.

const RECEIVER = '';   // receiver URL ending in /exec
const KEY = '';        // receiver key
const APP = 'https://6hdb2g4z5r-svg.github.io/loop-life/';

const C = {
  bg: new Color('#0c1117'), bg2: new Color('#151c24'), track: new Color('#232c36'), fg: new Color('#eef2f6'),
  mute: new Color('#8e9aa8'), dim: new Color('#5d6876'),
  green: new Color('#2fdc5d'), yellow: new Color('#f3d23c'), red: new Color('#ff4d5e'),
  sleep: new Color('#86aed3'), strain: new Color('#2b97f5'),
};
const recCol = v => v == null ? C.dim : v >= 67 ? C.green : v >= 34 ? C.yellow : C.red;
const scoreCol = v => v == null ? C.dim : v >= 80 ? C.green : v >= 60 ? C.yellow : C.red;

async function getState(name) {
  const r = new Request(`${RECEIVER}?key=${encodeURIComponent(KEY)}&action=state&name=${name}`);
  r.timeoutInterval = 25;
  return await r.loadJSON();
}

async function load() {
  const fm = FileManager.local(), cache = fm.joinPath(fm.cacheDirectory(), 'looplife-widget.json');
  const old = fm.fileExists(cache) ? JSON.parse(fm.readString(cache)) : null;
  try {
    const w = await getState('widget');
    if (!w || w.ok === false) throw new Error('no widget data');
    let nut = null;
    for (let i = 0; i < 2 && nut == null; i++) {
      try {
        const n = await getState('db_widget');
        const doc = n && n.docs && n.docs.nut;
        if (doc && doc.day === w.day) nut = doc.score;
        else break;
      } catch (e) {}
    }
    if (nut == null && old && old.day === w.day && old.nut != null) nut = old.nut;
    const out = Object.assign({}, w, {nut});
    fm.writeString(cache, JSON.stringify(out));
    return out;
  } catch (e) {   // offline or receiver hiccup: keep showing the last values
    return old;
  }
}

// Ring image: thick round-capped arc on a dark track, big number in the middle (like the app's dials).
function ringImage(value, max, color, unit) {
  const S = 150, W = 14, ctx = new DrawContext();
  ctx.size = new Size(S, S); ctx.opaque = false; ctx.respectScreenScale = true;
  const r = (S - W) / 2 - 2, cx = S / 2, cy = S / 2;
  const arc = (to, col) => {   // overlapping round dots = smooth stroke with round caps, colours always rendered
    ctx.setFillColor(col);
    const n = Math.max(1, Math.ceil(to * 360));
    for (let i = 0; i <= n; i++) {
      const a = -Math.PI / 2 + 2 * Math.PI * to * i / n;
      ctx.fillEllipse(new Rect(cx + r * Math.cos(a) - W / 2, cy + r * Math.sin(a) - W / 2, W, W));
    }
  };
  arc(1, C.track);
  const f = value == null ? 0 : Math.max(0, Math.min(1, value / max));
  if (f > 0) arc(f, color);
  const txt = value == null ? '–' : (unit === '%' || unit === 'score' ? String(Math.round(value)) : (+value).toFixed(1));
  const pct = unit === '%' && value != null;
  const bigSize = txt.length >= 4 ? 34 : 40, wBig = txt.length * bigSize * 0.58, wPct = pct ? 15 : 0;
  const x0 = cx - (wBig + wPct) / 2;
  ctx.setTextColor(C.fg);
  ctx.setFont(Font.boldRoundedSystemFont(bigSize)); ctx.setTextAlignedCenter();
  ctx.drawTextInRect(txt, new Rect(x0, cy - bigSize * 0.66, wBig, bigSize * 1.3));
  if (pct) {
    ctx.setFont(Font.boldRoundedSystemFont(17)); ctx.setTextAlignedLeft();
    ctx.drawTextInRect('%', new Rect(x0 + wBig, cy - 7, 22, 22));
  }
  return ctx.getImage();
}

const hm = m => m == null ? null : `${Math.floor(m / 60)}h${String(Math.round(m % 60)).padStart(2, '0')}`;

const d = await load();
const w = new ListWidget();
const g = new LinearGradient(); g.colors = [C.bg2, C.bg]; g.locations = [0, 1]; w.backgroundGradient = g;
w.url = APP; w.setPadding(12, 12, 10, 12);
w.refreshAfterDate = new Date(Date.now() + 20 * 60 * 1000);

if (!RECEIVER || !KEY || !d) {
  const t = w.addText(!RECEIVER || !KEY ? 'Loop Life: fill RECEIVER and KEY in the script' : 'Loop Life: no data yet');
  t.textColor = C.mute; t.font = Font.systemFont(12);
} else {
  // header: brand left, update time right
  const head = w.addStack(); head.layoutHorizontally(); head.centerAlignContent();
  const brand = head.addText('LOOP LIFE'); brand.font = Font.heavySystemFont(11); brand.textColor = C.fg;
  head.addSpacer();
  const when = d.built ? new Date(d.built.replace(' ', 'T') + ':00Z') : null;
  if (when) {
    const df = new DateFormatter(); df.dateFormat = 'HH:mm';
    const u = head.addText(df.string(when)); u.font = Font.mediumSystemFont(10); u.textColor = C.dim;
  }
  w.addSpacer(8);

  const items = [
    ['SLEEP', d.sleep, 100, C.sleep, '%', hm(d.asleep)],
    ['RECOVERY', d.rec, 100, recCol(d.rec), '%', d.hrv != null ? `HRV ${Math.round(d.hrv)}` : null],
    ['STRAIN', d.strain, 21, C.strain, '', d.steps != null ? `${(d.steps / 1000).toFixed(1)}k steps` : null],
    ['NUTRITION', d.nut, 100, scoreCol(d.nut), 'score', d.nut == null ? 'open app' : '/100'],
  ];
  const row = w.addStack(); row.layoutHorizontally(); row.topAlignContent();
  items.forEach(([label, v, max, col, unit, sub], i) => {
    if (i) row.addSpacer();
    const cell = row.addStack(); cell.layoutVertically(); cell.size = new Size(72, 0);
    const a = cell.addStack(); a.addSpacer();
    const img = a.addImage(ringImage(v, max, col, unit)); img.imageSize = new Size(66, 66);
    a.addSpacer();
    cell.addSpacer(6);
    const b = cell.addStack(); b.addSpacer();
    const t = b.addText(label); t.font = Font.boldSystemFont(9.5); t.textColor = C.fg; t.lineLimit = 1; t.minimumScaleFactor = 0.8;
    b.addSpacer();
    cell.addSpacer(1);
    const c = cell.addStack(); c.addSpacer();
    const s = c.addText(sub || ' '); s.font = Font.mediumSystemFont(9); s.textColor = C.mute; s.lineLimit = 1; s.minimumScaleFactor = 0.8;
    c.addSpacer();
  });
  w.addSpacer();
}

if (config.runsInWidget) Script.setWidget(w); else await w.presentMedium();
Script.complete();
