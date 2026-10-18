/* Loop Life weekly planner: decides today's day type (rest / recovery / light / train) from the athlete's rest-day rules,
   recovery and load. Single source of truth for the dashboard, every AI coach and the Telegram notifications.
   Pure function, no globals: llDayPlan(D, prof, T) */
var llDayPlan = (function () {
  const DAYS = [[0, /\b(sun(day)?|dimanche|dim)\b/i], [1, /\b(mon(day)?|lundi)\b/i], [2, /\b(tue(s|sday)?|mardi)\b/i], [3, /\b(wed(nesday)?|mercredi)\b/i],
    [4, /\b(thu(rs|rsday)?|jeudi)\b/i], [5, /\b(fri(day)?|vendredi|ven)\b/i], [6, /\b(sat(urday)?|samedi|sam)\b/i]];
  const NAMES_FR = ['dimanche', 'lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi'];
  const NAMES_EN = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const WALK = /walk|hiking|marche/i;
  const wd = d => new Date(d + 'T12:00:00Z').getUTCDay();
  const add = (d, n) => { const x = new Date(d + 'T12:00:00Z'); x.setUTCDate(x.getUTCDate() + n); return x.toISOString().slice(0, 10); };
  const trimp = x => { const z = (x && x.zones) || []; return (z[1] || 0) + 2 * (z[2] || 0) + 3 * (z[3] || 0) + 4 * (z[4] || 0) + 5 * (z[5] || 0); };
  const r1 = v => Math.round(v * 10) / 10;

  function rules(prof) {
    prof = prof || {};
    const txt = String(prof.objective || '');
    let allowed = Array.isArray(prof.restDays) && prof.restDays.length ? prof.restDays.map(Number) : null;
    if (!allowed) { const m = DAYS.filter(([, re]) => re.test(txt)).map(([n]) => n); allowed = /off|rest|repos|relâche/i.test(txt) && m.length ? m : null; }
    let per = +prof.restPerWeek || 0;
    if (!per) { const m = txt.match(/(\d)\s*(?:day|days|jour|jours)\s*(?:off|of rest|de repos|repos)/i); per = m ? +m[1] : 1; }
    allowed = (allowed || [0, 1, 2, 3, 4, 5, 6]).sort((a, b) => (a + 6) % 7 - (b + 6) % 7);
    return {allowed, configured: allowed.length < 7, per: Math.max(0, Math.min(3, per))};
  }

  return function (D, prof, T) {
    const order = D.order || Object.keys(D.days).sort(), days = D.days;
    T = T || order[order.length - 1];
    const x = days[T] || {}, i = order.indexOf(T), R = rules(prof), w = wd(T);
    // Banister load as of yesterday (CTL 42 d, ATL 7 d), same model as the dashboard
    const ka = 1 - Math.exp(-1 / 7), kc = 1 - Math.exp(-1 / 42); let atl = 0, ctl = 0;
    for (let j = 0; j < i; j++) { const t = trimp(days[order[j]]); atl += ka * (t - atl); ctl += kc * (t - ctl); }
    const tsb = r1(ctl - atl);
    let debt = 0; for (let j = Math.max(0, i - 6); j <= i; j++) { const y = days[order[j]]; if (y && y.sl) debt += Math.max(0, (y.need || 460) - y.sl.asleep); }
    // rest days already taken this week (Monday to yesterday): no training session and day strain < 8
    const mon = add(T, -((w + 6) % 7)), taken = [];
    for (let d = mon; d < T; d = add(d, 1)) { const y = days[d]; if (y && !(y.workouts || []).some(k => !WALK.test(k.type)) && (y.strain == null || y.strain < 8)) taken.push(d); }
    const owed = Math.max(0, R.per - taken.length);
    const left = []; for (let d = T; wd(d) !== 1 || d === T; d = add(d, 1)) { if (R.allowed.includes(wd(d))) left.push(d); if (wd(d) === 0) break; }
    const rec = x.rec, c = 6 + (rec == null ? 50 : rec) / 99 * 11;
    let band = [r1(Math.max(0, c - 1.5)), r1(Math.min(21, c + 1.5))];
    const tired = tsb < -30 || (rec != null && rec < 50), restWise = tired || debt > 240;
    let type = 'train', call = 'Train', fr = '', en = '', mandatory = false;
    const nm = d => NAMES_FR[wd(d)], nmE = d => NAMES_EN[wd(d)];
    if (rec != null && rec < 34) {
      type = 'recovery'; call = 'Active recovery'; band = [3, 8]; mandatory = true;
      fr = `Récupération rouge (${rec} %) : repos actif aujourd'hui, pas d'entraînement structuré.`; en = `Red recovery (${rec}%): active recovery only, no structured training.`;
    } else if (owed > 0 && R.allowed.includes(w) && (left.length <= owed || restWise)) {
      type = 'rest'; call = 'Rest'; band = [0, 7]; mandatory = left.length <= owed;
      const why = [tsb < -30 ? `fatigue accumulée élevée (TSB ${tsb})` : '', debt > 240 ? `dette de sommeil ${Math.floor(debt / 60)}h${String(Math.round(debt % 60)).padStart(2, '0')} sur 7 jours` : '', rec != null && rec < 50 ? `récupération ${rec} %` : ''].filter(Boolean);
      const whyE = [tsb < -30 ? `high accumulated fatigue (TSB ${tsb})` : '', debt > 240 ? `7-day sleep debt ${Math.round(debt)} min` : '', rec != null && rec < 50 ? `recovery ${rec}%` : ''].filter(Boolean);
      fr = mandatory ? `Jour de repos : c'est ton dernier jour de repos possible cette semaine${R.allowed.length < 7 ? ' (' + R.allowed.map(n => NAMES_FR[n]).join(', ') + ')' : ''} et tu n'en as pas encore pris${why.length ? ' ; en plus ' + why.join(', ') : ''}. ${rec != null ? `Même avec ${rec} % de récupération` : 'Quelle que soit ta récupération'}, pas d'entraînement : marche, mobilité, étirements.`
        : `Jour de repos conseillé aujourd'hui (jour off autorisé) : ${why.join(', ')}. Tu reprendras ${left.slice(1).map(nm).join(' ou ') || 'demain'}.`;
      en = mandatory ? `Rest day: last allowed rest day this week${R.allowed.length < 7 ? ' (' + R.allowed.map(n => NAMES_EN[n]).join(', ') + ')' : ''} and none taken yet${whyE.length ? '; also ' + whyE.join(', ') : ''}. Walk, mobility, stretching only.`
        : `Rest day recommended today (allowed day off): ${whyE.join(', ')}.`;
    } else {
      if (tired) { type = 'light'; call = 'Train light'; band = [r1(Math.max(4, band[0] - 2)), r1(Math.max(6, band[1] - 2))]; }
      const due = owed > 0 ? left.filter(d => d > T) : [];
      fr = (tired ? `Séance légère : ${[tsb < -30 ? `fatigue accumulée (TSB ${tsb})` : '', rec != null && rec < 50 ? `récupération ${rec} %` : ''].filter(Boolean).join(', ')}.` : `Jour d'entraînement (récupération ${rec ?? '–'} %).`) + (due.length ? ` Repos encore dû cette semaine : ${due.map(nm).join(' ou ')}.` : '');
      en = (tired ? 'Light session (fatigue signals).' : `Training day (recovery ${rec ?? '-'}%).`) + (due.length ? ` Rest day still due this week: ${due.map(nmE).join(' or ')}.` : '');
    }
    return {date: T, type, call, band, mandatory, fr, en, tsb, debt: Math.round(debt), restTaken: taken, restPerWeek: R.per, allowedDays: R.allowed, rulesFromSettings: R.configured,
      nextRest: owed > 0 ? (left.find(d => d > T) || null) : null};
  };
})();
if (typeof module !== 'undefined') module.exports = llDayPlan;
