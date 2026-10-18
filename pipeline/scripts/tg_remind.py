import sys, os, json, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tg_cards import *
args = [a for a in sys.argv[1:] if not a.startswith('--')]
dry = '--dry' in sys.argv
h = open(args[0], encoding='utf-8').read()
i = h.index('const D = ') + len('const D = ')
D = json.JSONDecoder().raw_decode(h, i)[0]
TG = args[1]
mode = args[2]
PLAN = {}
if len(args) > 3:
 try:
  PLAN = json.load(open(args[3]))
 except Exception:
  PLAN = {}
now = dt.datetime.now(dt.timezone.utc)
if mode == 'auto':
 mode = 'morning' if now.hour < 12 else 'midday' if now.hour < 15 else 'session' if now.hour < 18 else 'strain' if now.hour < 21 else 'bedtime'
days, order = (D['days'], D['order'])
d = now.date().isoformat() if now.date().isoformat() in days else order[-1]
x = days[d]
i = order.index(d)
lo, hi, CALLP, SESS, DP = today_plan(PLAN, D, d)
REST = bool(DP and DP['type'] in ('rest', 'recovery'))
op = PLAN.get('obj') or {}
if not str(op.get('key', '')).startswith(d):
 op = {}
JOURS = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']
MOIS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.']
dd = dt.date.fromisoformat(d)
LAB = f'{JOURS[dd.weekday()]} {dd.day} {MOIS[dd.month - 1]}'.upper()
CAN = Image is not None
age_h = (now.replace(tzinfo=None) - dt.datetime.strptime(D['built'], '%Y-%m-%d %H:%M')).total_seconds() / 3600
stale = f"\n<i>Données de {D['built'][11:16]} : appuie sur Synchro pour actualiser.</i>" if age_h > 3 else ''
CALL = {'Go hard': 'Pousse fort', 'Train': 'Entraîne-toi', 'Train light': 'Séance légère', 'Active recovery': 'Récupération active', 'Rest': 'Repos'}
STX = {'Ahead': 'en avance', 'On track': 'dans les temps', 'Behind': 'en retard', 'Too early to tell': 'trop tôt pour juger'}
PROF = PLAN.get('prof') or {}
WEEK = PLAN.get('week') or {}

def wday(k):
 for e in WEEK.get('days') or []:
  if e.get('date') == k:
   return e
 return None
GOAL = int(PROF.get('stepGoal') or 8000)

def steps_of(k):
 return (days.get(k) or {}).get('steps') or 0
ST = steps_of(d)
past = [k for k in order[:i]]
streak = 0
for k in reversed(past):
 if steps_of(k) >= GOAL:
  streak += 1
 else:
  break
avg7 = mean([steps_of(k) for k in past[-7:]]) or 0
max30 = max([steps_of(k) for k in past[-30:]] or [0])
hr_now = now.hour + now.minute / 60
exp_frac = max(0.05, min(1.0, (hr_now - 7.5) / 15))
EXP = round(GOAL * exp_frac)
LEFT = max(0, GOAL - ST)
WALK = round(LEFT / 105)
SPORT = [w for w in x.get('workouts') or [] if 'Walk' not in w.get('type', '')]
TOD = wday(d)
if TOD:
 import re as _re
 _m = _re.search('(\\d+(?:[.,]\\d+)?)\\s*[-–]\\s*(\\d+(?:[.,]\\d+)?)', str(TOD.get('strain') or ''))
 _b = (float(_m.group(1).replace(',', '.')), float(_m.group(2).replace(',', '.'))) if _m else None
 if TOD.get('type') in ('rest', 'recovery'):
  REST = True
  lo, hi = _b or (0, 7)
  SESS = 'Jour de repos prévu dans ton plan de la semaine : marche, mobilité, étirements.'
  DP = dict(DP or {}, type='rest', band=[lo, hi], mandatory=False, fr=SESS)
  CALLP = 'Rest'
 elif not (DP and DP.get('type') == 'recovery'):
  REST = False
  if _b:
   lo, hi = _b
  SESS = TOD.get('title') or SESS
  if DP and DP.get('type') == 'rest':
   DP = dict(DP, type='train', band=[lo, hi])
  if CALLP in ('Rest', 'Active recovery', None):
   CALLP = 'Train light' if TOD.get('type') == 'easy' else 'Train'
TOM = wday((dd + dt.timedelta(days=1)).isoformat())
TYPE_FR = {'rest': 'Repos', 'recovery': 'Récup', 'easy': 'Facile', 'quality': 'Qualité', 'long': 'Long', 'strength': 'Muscu', 'padel': 'Padel', 'cross': 'Croisé'}
WK_FR = {'TraditionalStrengthTraining': 'Musculation', 'FunctionalStrengthTraining': 'Renfo', 'Running': 'Course', 'Cycling': 'Vélo', 'Tennis': 'Tennis', 'Padel': 'Padel', 'HighIntensityIntervalTraining': 'HIIT', 'Swimming': 'Natation'}

def ok(v):
 return v not in (None, '', '-', '–')

def sess_meta(e):
 return ' · '.join([v for v in [e.get('when') if ok(e.get('when')) else '', e.get('duration') if ok(e.get('duration')) else '', 'effort ' + e['strain'] if ok(e.get('strain')) else '', 'FC ' + e['hr'] if ok(e.get('hr')) else ''] if v])

def sess_line(e):
 if not e:
  return ''
 bits = [e.get('title') or TYPE_FR.get(e.get('type'), '')]
 if ok(e.get('when')):
  bits.append('à ' + e['when'])
 if ok(e.get('duration')):
  bits.append(e['duration'])
 return ' · '.join(bits)

def steps_msg():
 if ST >= GOAL:
  m = f'<b>Objectif de pas atteint · {fmt(ST)}</b>'
  t = f'{fmt(ST)} / {fmt(GOAL)} pas. ' + ('Nouveau record sur 30 jours ! ' if max30 and ST > max30 else '') + (f'Série : {streak + 1} jours d’affilée.' if streak else 'Refais-le demain pour lancer une série.')
 else:
  diff = ST - EXP
  m = f'<b>{fmt(ST)} pas · {round(ST * 100 / GOAL)} % de ton objectif</b>'
  t = (f'En avance de {fmt(diff)} pas sur ton rythme. ' if diff >= 0 else f'En retard de {fmt(-diff)} pas sur ton rythme. ') + f'Il t’en manque {fmt(LEFT)} ≈ {WALK} min de marche.' + (f' Garde ta série de {streak} jours !' if streak else '')
 return (m, t)

def steps_card(c, y0):
 pct = ST / GOAL if GOAL else 0
 c.ring(W // 2, y0, 230, 32, pct, TEAL if pct < 1 else GREEN, str(round(pct * 100)), '%', 'OBJECTIF DE PAS', f'{fmt(ST)} / {fmt(GOAL)}')
 diff = ST - EXP
 return c.tiles(y0 + 330, [('Rythme', ('+' if diff >= 0 else '−') + fmt(abs(diff)), 'vs attendu à cette heure', GREEN if diff >= 0 else ORANGE), ('Série', f'{streak} j', f'≥ {fmt(GOAL)} pas'), ('Moy. 7 j', fmt(avg7), 'pas / jour')])

def sess_box(c, y, e, label):
 c.d.rounded_rectangle([60, y, W - 60, y + 250], 26, fill=CARD)
 c.text((88, y + 30), label, 22, MUTE, 'semi', spacing=2)
 c.wrap((88, y + 72), e.get('title') or '', 40, FG, 'bold', width=W - 176, maxlines=2)
 c.wrap((88, y + 184), sess_meta(e), 28, TEAL, 'semi', width=W - 176, maxlines=1)
 return y + 250

def week_recap():
 ks = [k for k in order if k > (dd - dt.timedelta(days=7)).isoformat() and k <= d]
 pk = [k for k in order if k > (dd - dt.timedelta(days=14)).isoformat() and k <= (dd - dt.timedelta(days=7)).isoformat()]
 ns = sum((len([w for w in days[k].get('workouts') or [] if 'Walk' not in w.get('type', '')]) for k in ks))
 a, b = (mean([steps_of(k) for k in ks]) or 0, mean([steps_of(k) for k in pk]) or 0)
 rr = mean([days[k].get('rec') for k in ks])
 return f"<b>Bilan de la semaine</b> : {ns} séance{('s' if ns > 1 else '')}, {fmt(a)} pas/jour ({('+' if a >= b else '−')}{fmt(abs(a - b))} vs semaine passée)" + (f', récupération moyenne {round(rr)} %.' if rr is not None else '.')
if mode == 'morning':
 r = x.get('rec')
 if r is None:
  tg_send(TG, f'<b>Ta récupération n’est pas encore calculée</b>\nLa nuit n’est pas arrivée sur le tableau de bord. Ouvre l’app Santé, lance « Sleep - today » depuis Spotlight, puis appuie sur Synchro.\n{link()}', dry=dry)
  sys.exit(0)
 col = rec_color(r)
 call = CALL.get(CALLP, CALLP or ('Entraîne-toi' if r >= 67 else 'Séance légère' if r >= 34 else 'Récupération active'))
 msg = [f'<b>Plan du jour · {call}</b>', f'Récupération {r} % · cible d’effort <b>{fmt(lo, 1)}–{fmt(hi, 1)}</b>.']
 if DP and DP['type'] != 'train' and (SESS != DP['fr']):
  msg.append(DP['fr'])
 if SESS:
  msg.append(f'Séance : {SESS}' if not REST else SESS)
 elif DP and DP.get('nextRest'):
  msg.append(f"Repos de la semaine prévu au plus tard le {dt.date.fromisoformat(DP['nextRest']).strftime('%d/%m')}.")
 if op and (not REST):
  msg.append(f"Objectif : {STX.get(op.get('status'), op.get('status', ''))}, ~{op.get('progress', '?')} % du chemin." + (f" Aujourd’hui : {op['today']}" if op.get('today') else ''))
 msg.append(link() + stale)
 photo = None
 if CAN:
  c = Card(1250)
  c.header('Plan du jour', LAB)
  c.ring(W // 2, 470, 250, 34, r / 100, col, str(r), '%', 'RÉCUPÉRATION', call.upper())
  c.band(800, 'Cible d’effort', lo, hi, x.get('strain'))
  y = 900
  if SESS:
   c.d.rounded_rectangle([60, y, W - 60, y + 270], 26, fill=CARD)
   c.text((88, y + 30), 'JOUR DE REPOS' if REST else 'SÉANCE CONSEILLÉE', 22, MUTE, 'semi', spacing=2)
   txt = ('Dernier jour de repos possible cette semaine. ' if DP and DP.get('mandatory') else '') + 'Pas d’entraînement : marche, mobilité, étirements.' if REST else SESS
   c.wrap((88, y + 74), txt, 34, FG, 'med', width=W - 176, maxlines=4)
  elif op:
   c.d.rounded_rectangle([60, y, W - 60, y + 200], 26, fill=CARD)
   c.text((88, y + 30), 'OBJECTIF', 22, MUTE, 'semi', spacing=2)
   c.wrap((88, y + 74), f"{STX.get(op.get('status'), '')} · {op.get('progress', '?')} %", 40, FG, 'bold')
  photo = c.save()
 tg_send(TG, '\n'.join(msg), photo, dry)
elif mode == 'midday':
 m, t = steps_msg()
 msg = [m, t]
 if REST:
  msg.append('Jour de repos : la marche compte, elle accélère la récupération sans fatiguer.')
 elif TOD and TOD.get('type') not in ('rest', 'recovery'):
  msg.append(f'Au programme : <b>{sess_line(TOD)}</b>.' + (f" Objectif : {TOD['goals'][0]}" if TOD.get('goals') else ''))
 elif SESS:
  msg.append('Au programme : ' + SESS)
 if LEFT > 0:
  msg.append('Idée : 15 min de marche après le déjeuner ≈ 1 600 pas et une glycémie plus stable.')
 msg.append(link() + stale)
 photo = None
 if CAN:
  box = bool(TOD and (not REST) and (TOD.get('type') not in ('rest', 'recovery')))
  c = Card(1310 if box else 1040)
  c.header('Point de mi-journée', LAB)
  y = steps_card(c, 470)
  if box:
   sess_box(c, y + 30, TOD, 'AU PROGRAMME AUJOURD’HUI')
  photo = c.save()
 tg_send(TG, '\n'.join(msg), photo, dry)
elif mode == 'session':
 if SPORT:
  w0 = SPORT[-1]
  s0 = x.get('strain') or 0
  nm = WK_FR.get(w0.get('type', ''), w0.get('type', 'Séance'))
  head = 'Séance faite' if s0 < lo else 'Cible atteinte'
  msg = [f'<b>{head} · bravo !</b>', f"{nm} {w0.get('dur', '?')} min, FC moy. {w0.get('avg', '–')} bpm, {fmt(w0.get('kcal'))} kcal. Effort du jour {fmt(s0, 1)} (cible {fmt(lo, 1)}–{fmt(hi, 1)})."]
  msg.append('Dans les 2 h : 30–40 g de protéines + des glucides pour transformer cette séance en progrès.')
  if op:
   msg.append(f"Objectif : {STX.get(op.get('status'), op.get('status', ''))}, ~{op.get('progress', '?')} % du chemin. Chaque séance compte.")
  if TOM:
   msg.append(f'Demain : {sess_line(TOM)}.')
  msg.append(link() + stale)
  photo = None
  if CAN:
   c = Card(1150)
   c.header('Séance terminée', LAB)
   c.ring(W // 2, 470, 250, 34, s0 / 21, GREEN, fmt(s0, 1), '', 'EFFORT DU JOUR', head.upper())
   c.band(800, 'Cible d’effort', lo, hi, s0)
   c.tiles(900, [(nm[:12], f"{w0.get('dur', '–')} min", w0.get('start', '')), ('FC moy.', str(w0.get('avg', '–')), f"max {w0.get('max', '–')}"), ('Calories', fmt(w0.get('kcal')), 'séance')])
   photo = c.save()
  tg_send(TG, '\n'.join(msg), photo, dry)
 elif REST or not (TOD or SESS) or (TOD and TOD.get('type') in ('rest', 'recovery')):
  m, t = steps_msg()
  msg = [m, t]
  if LEFT > 0:
   msg.append(f'Fin d’après-midi idéale pour bouger : {min(45, max(10, WALK))} min de marche rapide et c’est dans la poche.')
  if TOM and TOM.get('type') not in ('rest', 'recovery'):
   msg.append(f'Demain : {sess_line(TOM)}. Repose-toi bien ce soir.')
  msg.append(link() + stale)
  photo = None
  if CAN:
   c = Card(1040)
   c.header('Bouge encore', LAB)
   steps_card(c, 470)
   photo = c.save()
  tg_send(TG, '\n'.join(msg), photo, dry)
 else:
  e = TOD or {'title': SESS}
  msg = [f"<b>Ta séance · {e.get('title', '')}</b>", sess_meta(e)]
  if e.get('structure'):
   msg.append('\n'.join(['• ' + z for z in e['structure'][:5]]))
  if e.get('goals'):
   msg.append('🎯 ' + e['goals'][0])
  if e.get('benefits'):
   msg.append('💪 ' + e['benefits'][0])
  if op:
   msg.append(f"Objectif : ~{op.get('progress', '?')} % du chemin. Cette séance t’en rapproche.")
  msg.append('Avant : un en-cas glucidique 60–90 min avant et 500 ml d’eau.' + (f" Récupération {x['rec']} % : tu es prêt." if x.get('rec') is not None and x['rec'] >= 50 else ''))
  msg.append(link() + stale)
  photo = None
  if CAN:
   st = e.get('structure') or []
   c = Card(700 + 56 * min(5, len(st)) + (44 if st else 0) + (130 if e.get('goals') else 0))
   c.header('Ta séance du jour', LAB)
   y = sess_box(c, 200, e, 'AU PROGRAMME') + 40
   if st:
    c.text((60, y), 'DÉROULÉ', 22, MUTE, 'semi', spacing=2)
    y += 44
    for z in st[:5]:
     c.wrap((60, y), '• ' + z, 30, FG, 'reg', width=W - 120, maxlines=1)
     y += 56
   if e.get('goals'):
    y += 20
    c.text((60, y), 'OBJECTIF', 22, MUTE, 'semi', spacing=2)
    c.wrap((60, y + 40), e['goals'][0], 30, TEAL, 'semi', width=W - 120, maxlines=2)
    y += 130
   c.tiles(y, [('Récup', f"{x.get('rec')} %" if x.get('rec') is not None else '–', 'ce matin', rec_color(x.get('rec'))), ('Pas', fmt(ST), f'{round(ST * 100 / GOAL)} % objectif'), ('Cible', f'{fmt(lo, 1)}–{fmt(hi, 1)}', 'effort du jour')])
   photo = c.save()
  tg_send(TG, '\n'.join(msg), photo, dry)
elif mode == 'strain':
 s = x.get('strain') or 0
 if REST:
  head = 'Jour de repos respecté' if s <= hi else 'Trop d’effort pour un jour de repos'
  tip = 'Parfait : continue au calme ce soir, la récupération de cette nuit en profitera.' if s <= hi else 'Arrête-toi là pour aujourd’hui : dîner riche en protéines et glucides, écrans coupés tôt.'
 elif s < lo:
  gap = lo - s
  mins = round(min(90, max(15, gap * 9)))
  rb = x.get('bR') or x.get('rhr') or 60
  hrr = (D.get('hrmax') or 190) - rb
  z2 = (round(rb + 0.6 * hrr), round(rb + 0.7 * hrr))
  head = f'Encore {fmt(gap, 1)} pour ta cible'
  tip = f'Environ {mins} min en zone 2 ({z2[0]}–{z2[1]} bpm) suffisent : vélo d’intérieur ou footing facile. Termine au moins 2 h 30 avant le coucher.'
 elif s <= hi:
  head = 'Cible atteinte'
  tip = 'Tu es dans ta zone. Tu peux t’arrêter là : la récupération de cette nuit sera optimale.'
 else:
  head = 'Au-dessus de ta cible'
  tip = 'Lève le pied pour ce soir : protéines + glucides au dîner, écrans coupés tôt et coucher plus tôt pour récupérer.'
 msg = [f'<b>Effort {fmt(s, 1)} · {head}</b>', f"Cible {fmt(lo, 1)}–{fmt(hi, 1)} · {fmt(x.get('steps'))} pas · {fmt(x.get('cal'))} kcal.", tip]
 if x.get('stress') is not None and x['stress'] >= 1.5:
  msg.append(f"Stress moyen élevé ({fmt(x['stress'], 1)}/3) : 5 min de respiration lente (4 s inspire, 6 s expire) avant de dormir.")
 if ST >= GOAL:
  msg.append(f'Objectif de pas atteint ✔' + (f' · série de {streak + 1} jours' if streak else ''))
 elif LEFT:
  msg.append(f'Pas : encore {fmt(LEFT)} pour ton objectif ≈ {WALK} min de marche' + (f', pour garder ta série de {streak} jours.' if streak else '.'))
 if dd.weekday() == 6:
  msg.append(week_recap())
 msg.append(link() + stale)
 photo = None
 if CAN:
  c = Card(1150)
  c.header('Effort', LAB)
  c.ring(W // 2, 470, 250, 34, s / 21, BLUE, fmt(s, 1), '', 'EFFORT DU JOUR', head.upper())
  c.band(800, 'Cible d’effort', lo, hi, s)
  c.tiles(900, [('Pas', fmt(x.get('steps')), f"{fmt(x.get('dist'), 1)} km"), ('Calories', fmt(x.get('cal')), f"{fmt(x.get('active'))} actives"), ('Séances', str(len(x.get('workouts') or [])), ' · '.join((w['start'] for w in (x.get('workouts') or [])[:2])))])
  photo = c.save()
 tg_send(TG, '\n'.join(msg), photo, dry)
elif mode == 'bedtime':
 wakes = [days[k]['sl']['end'] for k in order[-7:] if days[k].get('sl')]
 wk = sum((int(w[:2]) * 60 + int(w[3:]) for w in wakes)) / len(wakes) if wakes else 480
 debt = sum((max(0, days[k]['need'] - days[k]['sl']['asleep']) for k in order[-7:] if days[k].get('sl')))
 r3 = [days[k]['sl']['asleep'] for k in order[-3:] if days[k].get('sl')]
 need = 460 + (sum((max(0, 460 - v) for v in r3)) / len(r3) * 0.5 if r3 else 0) + (x.get('strain') or 0) * 2.5
 bed = (wk - need / 0.94 - 10) % 1440
 clock = lambda m: f'{int(m // 60) % 24:02d}:{int(m % 60):02d}'
 msg = [f'<b>Heure de coucher · {clock(bed)}</b>', f"Pour dormir {hm(need)} (effort {fmt(x.get('strain'), 1)}, dette 7 j {hm(debt)}) et te lever vers {clock(wk)}.", f'À {clock((bed - 60) % 1440)} : écrans coupés, lumière tamisée. Chambre fraîche (18–19 °C). Garde la Watch au poignet pour mesurer ta VFC.']
 if TOM:
  msg.append(f'Demain : <b>{sess_line(TOM)}</b>' + (f" · {TOM['goals'][0]}" if TOM.get('goals') and TOM.get('type') not in ('rest', 'recovery') else '') + '. Une bonne nuit, c’est la moitié de la séance.')
 msg.append(link() + stale)
 photo = None
 if CAN:
  c = Card(1290 if TOM else 1150)
  c.header('Planificateur de sommeil', LAB)
  c.text((W // 2, 330), 'COUCHER CONSEILLÉ', 30, MUTE, 'semi', anchor='mm', spacing=5)
  c.text((W // 2, 470), clock(bed), 190, SLEEPC, 'bold', anchor='mm')
  c.text((W // 2, 610), f'réveil vers {clock(wk)}', 34, FG, 'med', anchor='mm')
  c.tiles(720, [('Besoin', hm(need), 'cette nuit'), ('Dette 7 j', hm(debt), 'à rattraper'), ('Écrans off', clock((bed - 60) % 1440), '1 h avant')])
  if TOM:
   sess_box(c, 920, TOM, 'DEMAIN')
  c.footer('Besoin = base 7h40 + dette des 3 dernières nuits + effort du jour')
  photo = c.save()
 tg_send(TG, '\n'.join(msg), photo, dry)
