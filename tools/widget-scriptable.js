// Loop Life — home-screen widget for the Scriptable app (iPhone).
// Shows the four dials of the dashboard: Recovery, Sleep, Strain, Nutrition. Tapping it opens Loop Life.
// Setup: paste this into a new Scriptable script, fill RECEIVER and KEY below (same values as in the Loop Life app
// settings), then add a medium Scriptable widget on the Home Screen and choose this script.
// The values stay on your phone; this repo is public, so never commit them filled in.

const RECEIVER = '';   // receiver URL ending in /exec
const KEY = '';        // receiver key
const APP = 'https://6hdb2g4z5r-svg.github.io/loop-life/';

const C = {
  bg: new Color('#0c1117'), track: new Color('#2a333e'), fg: new Color('#eef2f6'), mute: new Color('#8e9aa8'),
  green: new Color('#2fdc5d'), yellow: new Color('#f3d23c'), red: new Color('#ff4d5e'), dim: new Color('#5d6876'),
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
  try {
    const w = await getState('widget');
    if (!w || w.ok === false) throw new Error('no widget data');
    let nut = null;
    try {
      const n = await getState('db_widget');
      const doc = n && n.docs && n.docs.nut;
      if (doc && doc.day === w.day) nut = doc.score;
    } catch (e) {}
    const out = Object.assign({}, w, {nut});
    fm.writeString(cache, JSON.stringify(out));
    return out;
  } catch (e) {   // offline or receiver hiccup: show the last values
    return fm.fileExists(cache) ? JSON.parse(fm.readString(cache)) : null;
  }
}

function ringImage(value, max, color, text) {
  const S = 120, W = 12, ctx = new DrawContext();
  ctx.size = new Size(S, S); ctx.opaque = false; ctx.respectScreenScale = true;
  const r = (S - W) / 2 - 1, cx = S / 2, cy = S / 2;
  const arc = (to, col) => {
    const p = new Path(), steps = Math.max(2, Math.ceil(to * 90));
    for (let i = 0; i <= steps; i++) {
      const a = -Math.PI / 2 + 2 * Math.PI * to * i / steps;
      const pt = new Point(cx + r * Math.cos(a), cy + r * Math.sin(a));
      if (i) p.addLine(pt); else p.move(pt);
    }
    ctx.addPath(p); ctx.setStrokeColor(col); ctx.setLineWidth(W); ctx.strokePath();
  };
  arc(1, C.track);
  const f = value == null ? 0 : Math.max(0, Math.min(1, value / max));
  if (f > 0.005) arc(f, color);
  ctx.setTextAlignedCenter(); ctx.setTextColor(C.fg); ctx.setFont(Font.boldSystemFont(text.length > 3 ? 26 : 30));
  ctx.drawTextInRect(text, new Rect(0, cy - 19, S, 40));
  return ctx.getImage();
}

const d = await load();
const w = new ListWidget();
w.backgroundColor = C.bg; w.url = APP; w.setPadding(12, 8, 10, 8);
w.refreshAfterDate = new Date(Date.now() + 20 * 60 * 1000);

if (!RECEIVER || !KEY) {
  const t = w.addText('Loop Life: fill RECEIVER and KEY in the script'); t.textColor = C.fg; t.font = Font.systemFont(12);
} else if (!d) {
  const t = w.addText('Loop Life: no data yet'); t.textColor = C.mute; t.font = Font.systemFont(12);
} else {
  const items = [
    [d.rec, 100, recCol(d.rec), 'RECOVERY', d.rec == null ? '–' : `${d.rec}%`],
    [d.sleep, 100, C.sleep, 'SLEEP', d.sleep == null ? '–' : `${d.sleep}%`],
    [d.strain, 21, C.strain, 'STRAIN', d.strain == null ? '–' : d.strain.toFixed(1)],
    [d.nut, 100, scoreCol(d.nut), 'NUTRITION', d.nut == null ? '–' : `${d.nut}`],
  ];
  w.addSpacer();
  const row = w.addStack(); row.layoutHorizontally(); row.centerAlignContent();
  items.forEach(([v, max, col, label, text], i) => {
    if (i) row.addSpacer();
    const col1 = row.addStack(); col1.layoutVertically(); col1.centerAlignContent(); col1.size = new Size(70, 0);
    const top = col1.addStack(); top.addSpacer();
    const img = top.addImage(ringImage(v, max, col, text)); img.imageSize = new Size(62, 62);
    top.addSpacer();
    col1.addSpacer(5);
    const lab = col1.addStack(); lab.addSpacer();
    const t = lab.addText(label); t.font = Font.semiboldSystemFont(9); t.textColor = C.mute; t.lineLimit = 1;
    lab.addSpacer();
  });
  w.addSpacer();
  const foot = w.addStack(); foot.addSpacer();
  const when = d.built ? new Date(d.built.replace(' ', 'T') + ':00Z') : null;
  const f = foot.addText(when ? 'Updated ' + when.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}) : '');
  f.font = Font.systemFont(9); f.textColor = C.dim;
  foot.addSpacer();
}

if (config.runsInWidget) Script.setWidget(w); else await w.presentMedium();
Script.complete();
