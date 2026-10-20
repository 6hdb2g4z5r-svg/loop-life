"""Loop Life coach notifications (WHOOP-style), rule-based, no AI cost.

Called after every refresh and by the reminders schedule. Decides, from the latest
dashboard data, meals and profile, which short notifications are due right now, and
remembers what was already sent today (receiver blob "push_state") so each one fires
at most once a day.

  python3 coach.py dash.json [--dry] [--now 2026-10-18T19:30] [--prev prev_dash.json]
"""
import json, math, os, subprocess, sys, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import notify as N  # receiver helpers + push sender

args = [a for a in sys.argv[1:] if not a.startswith('--')]
DRY = '--dry' in sys.argv
def opt(name):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None

D = json.load(open(args[0]))
UTCNOW = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
def phone_offset():
    """Health data carry the phone's wall-clock time, so the phone's UTC offset (China = +8) is estimated from the
    newest sample vs real UTC. Stale data can only make the estimate too low, so a lower value is adopted only
    after 20 h without confirming the higher one (e.g. back home). Returns (offset, confirmed)."""
    st = N.rx_get('push_state') or {}
    keep = st.get('tz') if isinstance(st, dict) else None
    S = D.get('sync') or {}
    stamps = [S.get(k) for k in ('hr_any', 'watch_hr', 'steps') if S.get(k)]
    est = None
    try:
        last = max(dt.datetime.strptime(s[:16], '%Y-%m-%d %H:%M') for s in stamps)
        est = math.ceil((last - UTCNOW).total_seconds() / 3600 - 0.1)
        est = max(0, est)   # home is UTC+0: stale data must never push the estimate west of home
        if est > 14: est = None
    except Exception:
        est = None
    if keep:
        age = (UTCNOW - dt.datetime.fromisoformat(keep['t'])).total_seconds() / 3600
        if est is None or (est < keep.get('o', 0) and age < 20):
            return keep.get('o', 0), False
    return (est if est is not None else 0), est is not None
TZ_OFF, TZ_OK = (0, False) if opt('--now') else phone_offset()
now = dt.datetime.fromisoformat(opt('--now')) if opt('--now') else UTCNOW + dt.timedelta(hours=TZ_OFF)  # the phone's local time
T = now.date().isoformat()
H = now.hour + now.minute / 60
PREV = None
if opt('--prev'):
    try:
        PREV = json.load(open(opt('--prev')))
    except Exception:
        PREV = None

days, order = D['days'], D['order']
x = days.get(T) or {}

def docs(name):
    if DRY and os.path.exists(name + '.json'):
        j = json.load(open(name + '.json'))
    else:
        j = N.rx_get(name)
    return j.get('docs', {}) if isinstance(j, dict) else {}

prof = docs('db_settings').get('profile') or {}
meals = [m for m in docs('db_meals').values() if isinstance(m, dict)]
body = docs('db_body')

# ---------------------------------------------------------------- helpers
def fmt(n, d=0):
    if n is None:
        return '–'
    s = f'{n:,.{d}f}'.replace(',', ' ')
    return s.replace('.', ',')

def hm(m):
    m = round(m or 0)
    return f'{m // 60}h{m % 60:02d}'

def clock(m):
    m %= 1440
    return f'{int(m // 60):02d}:{int(m % 60):02d}'

def mean(a):
    a = [v for v in a if v is not None]
    return sum(a) / len(a) if a else None

def day_plan():
    try:
        p = 'dp_in.json'
        json.dump({'D': {'order': order, 'days': days}, 'prof': prof, 'T': T}, open(p, 'w'))
        js = "const f=require(process.argv[1]),a=JSON.parse(require('fs').readFileSync(process.argv[2],'utf8'));process.stdout.write(JSON.stringify(f(a.D,a.prof,a.T)))"
        r = subprocess.run(['node', '-e', js, os.path.join(HERE, 'scripts', 'dayplan.js'), p], capture_output=True, text=True, timeout=30)
        os.unlink(p)
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout else None
    except Exception:
        return None

DP = day_plan() if T in days else None
REST = bool(DP and DP['type'] in ('rest', 'recovery'))
lo, hi = (DP['band'] if DP else [None, None])
rec, strain, steps = x.get('rec'), x.get('strain') or 0, x.get('steps') or 0

# body weight / targets (same formulas as the dashboard)
weight = float(prof.get('weight') or 0) or None
if body:
    last = body[sorted(body)[-1]]
    weight = last.get('w') or weight
weight = weight or 65
GOAL_STEPS = int(prof.get('stepGoal') or 8000)
ADJ = {'lose': {'slow': -250, 'moderate': -450, 'fast': -650}, 'gain': {'slow': 150, 'moderate': 300, 'fast': 450},
       'recomp': {'slow': -150, 'moderate': -150, 'fast': -150}, 'maintain': {'slow': 0, 'moderate': 0, 'fast': 0}}
def targets():
    full = [k for k in order if k < T and (days[k].get('cal') or 0) > 1200][-14:]
    avg_cal = mean([days[k]['cal'] for k in full]) or 2100
    avg_rest = mean([days[k]['cal'] - (days[k].get('active') or 0) for k in full]) or 1500
    so = x.get('cal') or 0
    ts = (D.get('sync') or {}).get('watch_hr') or ''
    mins = int(ts[11:13]) * 60 + int(ts[14:16]) if ts[:10] == T else 1440
    burn = max(so + avg_rest / 1440 * (1440 - mins), so) if so else avg_cal
    age = (now.date() - dt.date.fromisoformat(prof.get('birth', '1994-02-10'))).days / 365.25
    bmr = 10 * weight + 6.25 * float(prof.get('height') or 163) - 5 * age + (-161 if prof.get('sex') == 'female' else 5)
    kcal = round(max(max(1200, bmr), burn + (ADJ.get(prof.get('goal'), ADJ['maintain']).get(prof.get('pace'), 0))))
    protein = round(weight * float(prof.get('proteinPerKg') or 1.8))
    return kcal, protein
KCAL_T, PROT_T = targets()
today_meals = [m for m in meals if m.get('date') == T]
eat_k = sum(float(m.get('kcal') or 0) for m in today_meals)
eat_p = sum(float(m.get('protein') or 0) for m in today_meals)
logs_food = any(m.get('date', '') >= (now.date() - dt.timedelta(days=3)).isoformat() for m in meals)

def step_streak():
    n = 0
    for k in reversed([k for k in order if k < T]):
        if (days[k].get('steps') or 0) >= GOAL_STEPS:
            n += 1
        else:
            break
    return n

def expected_steps():
    pts = [(7, 0), (10, .25), (14, .6), (17.5, .7), (21.5, 1)]
    if H <= 7:
        return 0
    if H >= 21.5:
        return GOAL_STEPS
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if H <= x1:
            return GOAL_STEPS * (y0 + (y1 - y0) * (H - x0) / (x1 - x0))
    return GOAL_STEPS

def bedtime():
    wakes = [days[k]['sl']['end'] for k in order[-7:] if days[k].get('sl')]
    wk = sum(int(w[:2]) * 60 + int(w[3:]) for w in wakes) / len(wakes) if wakes else 480
    r3 = [days[k]['sl']['asleep'] for k in order[-3:] if days[k].get('sl')]
    need = 460 + (sum(max(0, 460 - v) for v in r3) / len(r3) * 0.5 if r3 else 0) + strain * 2.5
    return (wk - need / 0.94 - 10) % 1440, wk, need

def sleep_debt():
    return sum(max(0, days[k]['need'] - days[k]['sl']['asleep']) for k in order[-7:] if days[k].get('sl'))

WK_FR = {'TraditionalStrengthTraining': 'Musculation', 'FunctionalStrengthTraining': 'Renforcement', 'Running': 'Course', 'Cycling': 'Vélo',
         'Tennis': 'Tennis', 'Padel': 'Padel', 'HighIntensityIntervalTraining': 'HIIT', 'Swimming': 'Natation', 'Yoga': 'Yoga',
         'Elliptical': 'Elliptique', 'Rowing': 'Rameur', 'CoreTraining': 'Gainage', 'Soccer': 'Football'}

# ---------------------------------------------------------------- rules
due = []   # (key, priority, title, body, is_event)
def add(key, title, body, event=False, prio=5):
    due.append((key, prio, title, body, event))

if T in days and 7 <= H < 23:
    # 1. Morning recovery (as soon as last night + recovery are in)
    if rec is not None and x.get('sl') and H < 14:
        zone = '🟢' if rec >= 67 else '🟡' if rec >= 34 else '🔴'
        hrv, bh, rhr, br = x.get('hrv'), x.get('bH'), x.get('rhr'), x.get('bR')
        bits = []
        if hrv and bh:
            bits.append(f'VFC {fmt(hrv)} ms ({"+" if hrv >= bh else "−"}{fmt(abs(hrv - bh))})')
        if rhr:
            bits.append(f'FC repos {rhr}')
        bits.append(f'sommeil {hm(x["sl"]["asleep"])} / {hm(x.get("need"))}')
        if rec >= 67:
            head = 'prêt pour l’effort'
        elif rec >= 34:
            head = 'effort modéré'
        else:
            head = 'journée de récupération'
        plan = ''
        if DP:
            if DP['type'] in ('rest', 'recovery'):
                plan = 'Jour de repos : marche, mobilité, étirements.'
            else:
                plan = f'Cible d’effort {fmt(lo, 1)}–{fmt(hi, 1)}' + (' (séance légère).' if DP['type'] == 'light' else '.')
        debt = sleep_debt()
        tail = f' Dette de sommeil {hm(debt)} sur 7 j.' if debt >= 150 else ''
        add('rec', f'{zone} Récupération {rec} % · {head}', ' · '.join(bits) + '.\n' + plan + tail, event=True, prio=1)
        # elevated resting HR / low HRV = early warning
        if rhr and br and hrv and bh and rhr - br >= 5 and hrv < bh * 0.85:
            add('rhr', f'FC de repos élevée · +{round(rhr - br)} bpm',
                'Avec une VFC basse, c’est un signe de fatigue, de stress ou d’un début de maladie. Hydrate-toi et garde l’effort léger aujourd’hui.', event=True, prio=2)

    # 2. Workouts (each new one, once)
    for w in x.get('workouts') or []:
        if 'Walk' in w.get('type', '') or 'Hik' in w.get('type', ''):
            continue
        nm = WK_FR.get(w.get('type', ''), w.get('type', 'Séance'))
        add('wk_' + w.get('start', '').replace(':', ''), f'Séance enregistrée · {nm} {w.get("dur", "?")} min',
            f'FC moy. {w.get("avg", "–")} · {fmt(w.get("kcal"))} kcal · effort du jour {fmt(strain, 1)}.\n'
            'Dans les 2 h : 30–40 g de protéines + des glucides pour récupérer.', event=True, prio=2)

    # 3. Strain vs target
    if DP and lo is not None:
        if REST and strain > hi:
            add('rest_over', f'Jour de repos · effort {fmt(strain, 1)}', f'Tu dépasses ta cible de repos (≤ {fmt(hi, 1)}). Garde le reste de la journée calme.', event=True, prio=2)
        elif not REST and lo <= strain <= hi + 1.5:
            add('strain_hit', f'Cible d’effort atteinte · {fmt(strain, 1)}', f'Tu es dans ta zone ({fmt(lo, 1)}–{fmt(hi, 1)}). Au-delà, la récupération de demain en pâtit.', event=True, prio=2)
        if not REST and strain > hi + 1.5:
            add('strain_over', f'Au-dessus de ta cible · {fmt(strain, 1)}', 'Lève le pied pour aujourd’hui : glucides + protéines au dîner et coucher plus tôt.', event=True, prio=2)
        if not REST and 18 <= H < 20 and strain < lo - 1:
            rb = x.get('bR') or x.get('rhr') or 60
            hrr = (D.get('hrmax') or 190) - rb
            mins = round(min(90, max(15, (lo - strain) * 9)))
            add('strain_low', f'Effort {fmt(strain, 1)} · cible {fmt(lo, 1)}–{fmt(hi, 1)}',
                f'≈ {mins} min en zone 2 ({round(rb + .6 * hrr)}–{round(rb + .7 * hrr)} bpm) suffisent : vélo ou footing facile, fini 2 h 30 avant le coucher.', prio=4)

    # 4. Steps
    exp = expected_steps()
    streak = step_streak()
    if steps >= GOAL_STEPS and H >= 9:
        add('steps_done', f'Objectif de pas atteint · {fmt(steps)}', (f'Série : {streak + 1} jours d’affilée. ' if streak else '') + 'Bien joué.', event=True, prio=3)
    elif 14.5 <= H < 17 and steps < exp * 0.8:
        gap = round(exp - steps)
        add('steps_mid', f'Pas : {fmt(steps)} · en retard sur ton rythme',
            f'{fmt(gap)} pas de retard pour l’objectif de {fmt(GOAL_STEPS)}. 15 min de marche maintenant ≈ 1 600 pas.', prio=4)
    elif 18.5 <= H < 21 and steps < GOAL_STEPS:
        left = GOAL_STEPS - steps
        add('steps_eve', f'Encore {fmt(left)} pas pour ton objectif', f'≈ {round(left / 105)} min de marche.' + (f' Ta série de {streak} jour{"s" if streak > 1 else ""} est en jeu.' if streak else ''), prio=4)

    # 5. Nutrition (only when meals are being logged)
    if logs_food:
        if 14 <= H < 16 and not today_meals:
            add('meal_none', 'Rien de loggé aujourd’hui', f'Prends ton repas en photo dans Loop Life · cible {fmt(KCAL_T)} kcal, {PROT_T} g de protéines.', prio=5)
        if 16 <= H < 18 and today_meals and eat_p < PROT_T * 0.45:
            add('prot_mid', f'Protéines : {round(eat_p)} / {PROT_T} g', f'Il t’en reste {round(PROT_T - eat_p)} g. En-cas : skyr + thon ≈ 45 g.', prio=4)
        if 20 <= H < 22 and today_meals and eat_p < PROT_T * 0.8:
            add('prot_eve', f'Encore {round(PROT_T - eat_p)} g de protéines', 'Pour le dîner : 200 g de poulet ou de poisson ≈ 50–60 g.', prio=4)
        if 19.5 <= H < 23 and eat_k > KCAL_T * 1.05:
            add('kcal_over', f'Calories : {fmt(eat_k)} / {fmt(KCAL_T)}', f'{fmt(eat_k - KCAL_T)} kcal au-dessus de ta cible. Rien de plus ce soir, ça se rattrape demain.', prio=4)

    # 6. Bedtime planner (wind-down)
    bed, wake, need = bedtime()
    mins_now = H * 60
    to_bed = (bed - mins_now) % 1440
    if 15 <= to_bed <= 60 and H >= 20:
        add('bed', f'Coucher conseillé {clock(bed)}', f'Pour dormir {hm(need)} et te lever vers {clock(wake)}. Écrans off, lumière tamisée, chambre fraîche.', prio=3)

    # 7. No fresh data during the day
    try:
        built = dt.datetime.strptime(D['built'][:16], '%Y-%m-%d %H:%M')
        if 10 <= H < 22 and (now - built).total_seconds() > 3 * 3600:
            add('nodata', 'Pas de nouvelles données depuis 3 h', 'Ouvre WhatsApp ou Health Auto Export (iPhone déverrouillé) pour synchroniser.', prio=6)
    except Exception:
        pass

    # 8. Weekly recap (Sunday evening)
    if now.weekday() == 6 and 20 <= H < 22.5:
        ks = [k for k in order if k > (now.date() - dt.timedelta(days=7)).isoformat() and k <= T]
        ns = sum(len([w for w in days[k].get('workouts') or [] if 'Walk' not in w.get('type', '')]) for k in ks)
        st = mean([days[k].get('steps') for k in ks]) or 0
        rr = mean([days[k].get('rec') for k in ks])
        sl = mean([days[k]['sl']['asleep'] for k in ks if days[k].get('sl')])
        add('week', 'Bilan de la semaine', f'{ns} séance{"s" if ns > 1 else ""} · {fmt(st)} pas/jour' + (f' · récup. moy. {round(rr)} %' if rr is not None else '') + (f' · sommeil {hm(sl)}' if sl else '') + '.', prio=5)

# ---------------------------------------------------------------- dedupe, pacing, send
DRYSTATE = 'push_state_dry.json'
state = (N.rx_get('push_state') or {}) if not DRY else (json.load(open(DRYSTATE)) if os.path.exists(DRYSTATE) else {})
if state.get('date') != T:
    state = {'date': T, 'sent': {}, 'last': 0}
sent = state['sent']
now_ts = now.timestamp()
GAP = 40 * 60          # min spacing between two non-event notifications
CAP = 9                # max notifications a day

out = []
for key, prio, title, body, event in sorted(due, key=lambda d: d[1]):
    if key in sent:
        continue
    if key == 'strain_hit' and 'strain_over' in sent:
        continue
    if len(sent) + len(out) >= CAP:
        break
    if not event and (now_ts - state.get('last', 0) < GAP or any(not o[3] for o in out)):
        continue
    out.append((key, title, body, event))

for key, title, body, event in out:
    if DRY:
        print(f'[{now:%H:%M}] {title}\n         {body.replace(chr(10), chr(10) + "         ")}')
        ok = True
    else:
        ok = N.push_raw(title, body)
    if ok:
        sent[key] = f'{now:%H:%M}'
        state['last'] = now_ts
if out and not DRY:
    if TZ_OK: state['tz'] = {'o': TZ_OFF, 't': UTCNOW.isoformat(timespec='seconds')}
    N.rx_put('push_state', state)
if DRY:
    json.dump(state, open(DRYSTATE, 'w'))
if not out:
    print('coach: nothing due' + (f' ({len(due)} already sent)' if due else ''))
