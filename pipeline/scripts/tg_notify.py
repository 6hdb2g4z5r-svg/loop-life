import sys, os, json, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tg_cards import *

def load_page(p):
 try:
  h = open(p, encoding='utf-8').read()
  i = h.index('const D = ') + len('const D = ')
  return json.JSONDecoder().raw_decode(h, i)[0]
 except Exception:
  return {'days': {}, 'sync': {}, 'order': []}
args = [a for a in sys.argv[1:] if not a.startswith('--')]
dry, empty = ('--dry' in sys.argv, '--empty' in sys.argv)
O = load_page(args[0])
TG = args[2]
PLAN = {}
if len(args) > 3:
 try:
  PLAN = json.load(open(args[3]))
 except Exception:
  PLAN = {}
now = dt.datetime.now(dt.timezone.utc)
if empty:
 sy = O.get('sync', {})
 try:
  age = (now.replace(tzinfo=None) - dt.datetime.strptime(str(O.get('built', ''))[:16], '%Y-%m-%d %H:%M')).total_seconds() / 3600
 except Exception:
  age = 99
 if not (3 <= age < 4 and 9 <= now.hour < 23):
  print('telegram: skipped (no new data, last data', round(age, 1), 'h ago)')
  sys.exit(0)
 tg_send(TG, f"<b>Synchro {now:%H:%M} · aucune nouvelle donnée</b>\nL’iPhone n’a rien envoyé depuis 3 h ({str(O.get('built', ''))[11:16]}). Dernières mesures : Watch {str(sy.get('watch_hr') or '-')[11:16]}, G Band {str(sy.get('gband') or '-')[11:16]}.\nDéverrouille l’iPhone et ouvre Health Auto Export : l’app Santé est verrouillée tant que le téléphone l’est.", dry=dry)
 sys.exit(0)
N = json.load(open(args[1]))
od, nd = (O.get('days', {}), N['days'])
T = N['order'][-1]
n, o = (nd.get(T) or {}, od.get(T) or {})
JOURS = ['lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.', 'dim.']
MOIS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.']

def lab(d):
 x = dt.date.fromisoformat(d)
 return f'{JOURS[x.weekday()]} {x.day} {MOIS[x.month - 1]}'
WT = {'TraditionalStrengthTraining': 'Musculation', 'FunctionalStrengthTraining': 'Renforcement', 'Tennis': 'Tennis', 'Padel': 'Padel', 'Running': 'Course', 'OutdoorRun': 'Course', 'IndoorRun': 'Course sur tapis', 'Walking': 'Marche', 'OutdoorWalk': 'Marche', 'Cycling': 'Vélo', 'IndoorCycling': 'Vélo d’intérieur', 'HighIntensityIntervalTraining': 'HIIT', 'Swimming': 'Natation', 'Soccer': 'Football', 'CrossTraining': 'Cross-training', 'CoreTraining': 'Gainage', 'Yoga': 'Yoga'}
lo, hi, CALLP, SESS, DP = today_plan(PLAN, N, T)
REST = bool(DP and DP['type'] in ('rest', 'recovery'))
sent = 0

def zone_word(r):
 return 'verte' if r >= 67 else 'jaune' if r >= 34 else 'rouge'
CAN = Image is not None
sl = n.get('sl')
if sl and (not o.get('sl')):
 a = sleep_arch(sl)
 need = n.get('need') or 460
 perf = n.get('sleep')
 pct = round(sl['asleep'] / need * 100)
 debt = max(0, need - sl['asleep'])
 msg = [f"<b>Sommeil · {hm(sl['asleep'])} sur {hm(need)} nécessaires</b>"]
 msg.append(f"Performance {perf} % · couché {sl['start']}, levé {sl['end']} · efficacité {a.get('eff')} %.")
 if a.get('staged'):
  msg.append(f"Profond {sl['deep']} min ({a['deep']} %), paradoxal {sl['rem']} min ({a['rem']} %), {a['wakes']} réveil{('s' if a['wakes'] > 1 else '')}.")
 if a.get('staged') and a['deep'] is not None and (a['deep'] < 13):
  msg.append('Sommeil profond sous la norme (13–23 %) : évite l’entraînement intense et les repas lourds après 20 h ce soir.')
 if debt >= 30:
  msg.append(f'Il te manque {hm(debt)} : avance ton coucher ce soir pour rattraper.')
 msg.append(link())
 photo = None
 if CAN:
  c = Card(1350)
  c.header('Sommeil', lab(T).upper())
  c.ring(W // 2, 470, 250, 34, (perf or 0) / 100, SLEEPC, str(perf if perf is not None else '–'), '%', 'PERFORMANCE', f"{hm(sl['asleep'])} / {hm(need)}")
  y = c.tiles(800, [('Profond', f"{sl['deep']} min", f"{a.get('deep') or '–'} %"), ('Paradoxal', f"{sl['rem']} min", f"{a.get('rem') or '–'} %"), ('Efficacité', f"{a.get('eff')} %", f"{a['wakes']} réveils")])
  c.hypno(y + 40, sl.get('hyp') or [], sl['start'], sl['end'])
  c.footer('Source : ' + {'watch': 'Apple Watch', 'gband': 'G Band'}.get(str(sl.get('src')), str(sl.get('src') or '-')))
  photo = c.save()
 tg_send(TG, '\n'.join(msg), photo, dry)
 sent += 1
if n.get('rec') is not None and o.get('rec') is None:
 r = n['rec']
 hv = hrv_view(N, T)
 col = rec_color(r)
 verdict = DP['fr'] if REST else {'verte': 'Ton corps est prêt pour une grosse charge.', 'jaune': 'Récupération moyenne : entraîne-toi en gardant de la marge.', 'rouge': 'Ton corps récupère encore : priorité au repos actif.'}[zone_word(r)]
 if DP and DP['type'] == 'light':
  verdict = DP['fr']
 elif DP and DP['type'] == 'train' and DP.get('nextRest'):
  verdict += f" Repos de la semaine prévu {dt.date.fromisoformat(DP['nextRest']).strftime('%d/%m')} au plus tard."
 msg = [f'<b>Récupération {r} % · ' + (DAYTYPE_FR[DP['type']].lower() if REST else f'zone {zone_word(r)}') + '</b>', verdict]
 if n.get('hrv'):
  msg.append(f"VFC {fmt(n['hrv'], 1)} ms (base {fmt(n.get('bH'), 1)}) · FC repos {n.get('rhr')} bpm (base {fmt(n.get('bR'), 1)}).")
 if hv.get('roll7'):
  msg.append(f"Tendance 7 jours : {fmt(hv['roll7'], 1)} ms, " + {'below': 'sous ta plage normale', 'above': 'au-dessus de ta plage normale', 'normal': 'dans ta plage normale'}.get(hv['band'], '') + f" ({fmt(hv['lo'], 1)}–{fmt(hv['hi'], 1)}).")
 if hv.get('outlier'):
  msg.append('La mesure de VFC de cette nuit s’écarte fortement de ta tendance : elle est probablement surestimée, fie-toi à la tendance 7 jours.')
 if hv.get('hrv_high30'):
  msg.append('Record : ta VFC la plus haute depuis 30 jours.')
 if hv.get('rhr_low30'):
  msg.append('Record : ta FC repos la plus basse depuis 30 jours.')
 if hv.get('rhr_z') is not None and hv['rhr_z'] >= 2:
  msg.append(f"Alerte : FC repos nettement au-dessus de ta normale ({hv['rhr_z']} écarts-types). Fatigue, stress, alcool ou début d’infection possibles.")
 msg.append(f'Cible d’effort du jour : <b>{fmt(lo, 1)}–{fmt(hi, 1)}</b>' + (' (repos)' if REST else '') + '.')
 if SESS and SESS != verdict:
  msg.append(f'Plan du coach : {SESS}')
 msg.append(link())
 photo = None
 if CAN:
  c = Card(1250)
  c.header('Récupération', lab(T).upper())
  c.ring(W // 2, 470, 250, 34, r / 100, col, str(r), '%', 'RÉCUPÉRATION', DAYTYPE_FR[DP['type']].upper() if DP else zone_word(r).upper())
  dh = round((n['hrv'] - n['bH']) / n['bH'] * 100) if n.get('hrv') and n.get('bH') else None
  dr = round(n['rhr'] - n['bR']) if n.get('rhr') and n.get('bR') else None
  c.tiles(800, [('VFC', f"{fmt(n.get('hrv'), 0)} ms", f"{('+' if (dh or 0) > 0 else '')}{(dh if dh is not None else '–')} % vs base", GREEN if (dh or 0) >= 0 else YELLOW), ('FC repos', f"{n.get('rhr') or '–'} bpm", f"{('+' if (dr or 0) > 0 else '')}{(dr if dr is not None else '–')} vs base", GREEN if (dr or 0) <= 0 else YELLOW), ('Sommeil', f"{(n.get('sleep') if n.get('sleep') is not None else '–')} %", hm(sl['asleep']) if sl else '')])
  c.band(1010, 'Cible d’effort', lo, hi, None)
  c.footer('Tendance VFC 7 j : ' + (f"{fmt(hv['roll7'], 1)} ms" if hv.get('roll7') else '–'))
  photo = c.save()
 tg_send(TG, '\n'.join(msg), photo, dry)
 sent += 1
for d in N['order'][-2:]:
 nn, oo = (nd.get(d) or {}, od.get(d) or {})
 seen = {w.get('start') for w in oo.get('workouts', [])}
 for w in nn.get('workouts', []):
  if w.get('start') in seen:
   continue
  name = WT.get(w['type'], w['type'])
  rb = nn.get('bR') or nn.get('rhr') or 60
  hrr = (N.get('hrmax') or 190) - rb
  z = [0] * 6
  hrs = w.get('hrs') or []
  for k, p in enumerate(hrs):
   dtm = min(5, hrs[k + 1][0] - p[0]) if k + 1 < len(hrs) else 1
   q = (p[1] - rb) / hrr
   z[0 if q < 0.5 else 1 if q < 0.6 else 2 if q < 0.7 else 3 if q < 0.8 else 4 if q < 0.9 else 5] += dtm
  pctr = round((w['avg'] - rb) / hrr * 100) if w.get('avg') else None
  secs = w.get('secs') or w['dur'] * 60
  pace = f"{int(secs / w['dist'] // 60)}:{int(secs / w['dist'] % 60):02d}" if w.get('dist') else None
  main = max(range(1, 6), key=lambda i: z[i]) if sum(z[1:]) else None
  msg = [f'<b>Activité détectée · {name}</b>', f"{w['start']}–{w['end']} · {w['dur']} min · {w['kcal']} kcal · FC moy {w['avg']} ({pctr} % de ta réserve), max {w['max']}."]
  if w.get('dist'):
   msg.append(f"{fmt(w['dist'], 2)} km à {pace}/km" + (f" · cadence {w['cad']}" if w.get('cad') else '') + (f" · VO₂max estimée {fmt(w['vo2e'], 1)}" if w.get('vo2e') else '') + '.')
  if main:
   msg.append(f"Surtout en zone {main} ({round(z[main])} min). Effort de la journée : {fmt(nn.get('strain'), 1)} / cible {fmt(lo, 1)}–{fmt(hi, 1)}.")
  if w.get('hrr1') is not None:
   msg.append(f"Récupération cardiaque 1 min : −{w['hrr1']} bpm" + (' (bonne forme aérobie).' if w['hrr1'] >= 25 else ' (à surveiller, < 25).' if w['hrr1'] < 18 else '.'))
  msg.append('Recharge : 20–40 g de protéines et des glucides dans l’heure qui suit, et 500 ml d’eau.')
  msg.append(link('Voir l’analyse du coach'))
  photo = None
  if CAN:
   c = Card(1250)
   c.header(name, (lab(d) + ' · ' + w['start']).upper())
   c.ring(W // 2, 470, 250, 34, (nn.get('strain') or 0) / 21, BLUE, fmt(nn.get('strain'), 1), '', 'EFFORT DU JOUR', f'cible {fmt(lo, 1)}–{fmt(hi, 1)}')
   t1 = ('Distance', f"{fmt(w['dist'], 2)} km", f'{pace}/km') if w.get('dist') else ('Durée', f"{w['dur']} min", f"{w['start']}–{w['end']}")
   c.tiles(800, [t1, ('FC moy', f"{w['avg']} bpm", f"max {w['max']}"), ('Calories', f"{w['kcal']}", 'kcal actives')])
   c.zones(1010, z)
   photo = c.save()
  tg_send(TG, '\n'.join(msg), photo, dry)
  sent += 1
ns, os_ = (n.get('strain'), o.get('strain'))
if ns is not None and os_ is not None:
 if REST and os_ <= hi < ns:
  tg_send(TG, f'<b>Jour de repos · effort {fmt(ns, 1)}</b>\nAujourd’hui est ton jour de repos (cible ≤ {fmt(hi, 1)}). Garde le reste de la journée calme : marche, mobilité, pas de séance.\n{link()}', dry=dry)
  sent += 1
 elif REST:
  pass
 elif os_ < lo <= ns:
  tg_send(TG, f'<b>Cible d’effort atteinte · {fmt(ns, 1)}</b>\nTu es dans ta zone du jour ({fmt(lo, 1)}–{fmt(hi, 1)}). Au-delà de {fmt(hi, 1)}, le coût en récupération dépasse le bénéfice pour demain.\n{link()}', dry=dry)
  sent += 1
 elif os_ <= hi + 1.5 < ns:
  tg_send(TG, f'<b>Effort au-dessus de ta cible · {fmt(ns, 1)}</b>\nTu dépasses ta zone du jour ({fmt(lo, 1)}–{fmt(hi, 1)}). Coupe l’intensité pour aujourd’hui, mange glucides + protéines et vise un coucher plus tôt.\n{link()}', dry=dry)
  sent += 1
if not sent:
 steps_d = (n.get('steps') or 0) - (o.get('steps') or 0)
 if REST:
  tg_send(TG, f"<b>Synchro {str(N['built'])[11:16]}</b> · jour de repos · effort {fmt(ns, 1)} (≤ {fmt(hi, 1)}) · {fmt(n.get('steps'))} pas · {fmt(n.get('cal'))} kcal.\n{link()}", dry=dry)
  sys.exit(0)
 pos = 'sous ta cible' if (ns or 0) < lo else 'dans ta cible' if (ns or 0) <= hi else 'au-dessus de ta cible'
 left = f' · encore {fmt(lo - (ns or 0), 1)} pour l’atteindre' if (ns or 0) < lo else ''
 tg_send(TG, f"<b>Synchro {str(N['built'])[11:16]}</b> · effort {fmt(ns, 1)} {pos} ({fmt(lo, 1)}–{fmt(hi, 1)}){left} · {fmt(n.get('steps'))} pas" + (f' (+{fmt(steps_d)})' if steps_d > 0 else '') + f" · {fmt(n.get('cal'))} kcal.\n{link()}", dry=dry)
