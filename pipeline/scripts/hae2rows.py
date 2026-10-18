import json, re
MAP = {'heart_rate': 'HeartRate', 'heart_rate_variability': 'HeartRateVariabilitySDNN', 'resting_heart_rate': 'RestingHeartRate', 'respiratory_rate': 'RespiratoryRate', 'step_count': 'StepCount', 'active_energy': 'ActiveEnergyBurned', 'basal_energy_burned': 'BasalEnergyBurned', 'resting_energy': 'BasalEnergyBurned', 'walking_running_distance': 'DistanceWalkingRunning', 'vo2_max': 'VO2Max', 'blood_oxygen_saturation': 'OxygenSaturation', 'oxygen_saturation': 'OxygenSaturation', 'body_temperature': 'BodyTemperature', 'blood_glucose': 'BloodGlucose', 'weight_body_mass': 'BodyMass', 'body_mass': 'BodyMass', 'apple_exercise_time': 'AppleExerciseTime', 'walking_heart_rate_average': 'WalkingHeartRateAverage'}
GBAND_TYPES = {'OxygenSaturation', 'BodyTemperature', 'BloodGlucose', 'BloodPressureSystolic', 'BloodPressureDiastolic'}
SLEEP_VAL = {'core': 'AsleepCore', 'deep': 'AsleepDeep', 'rem': 'AsleepREM', 'awake': 'Awake', 'in bed': 'InBed', 'inbed': 'InBed', 'asleep': 'AsleepUnspecified', 'unspecified': 'AsleepUnspecified'}

def ts(s):
 return str(s).replace('T', ' ')[:19] if s else None

def src(s, t=None):
 s = s or ''
 parts = [p.strip() for p in s.split('|') if p.strip()]
 if t in GBAND_TYPES and (not parts or any(('G Band' in p for p in parts))):
  return 'G Band'
 watch = [p for p in parts if 'Apple' in p and 'Watch' in p]
 if watch:
  return watch[0]
 if parts == ['G Band']:
  return 'G Band'
 return parts[0] if parts else 'HAE'

def num(x):
 if isinstance(x, dict):
  x = x.get('qty', x.get('Avg'))
 try:
  return float(x)
 except Exception:
  return None

def _km(q):
 if not isinstance(q, dict):
  return num(q)
 v, u = (num(q), (q.get('units') or '').lower())
 if v is None:
  return None
 return v / 1000 if u == 'm' else v * 1.609344 if u in ('mi', 'mile') else v

def wdetail(w, st, en):
 from datetime import datetime
 P = lambda x: datetime.strptime(ts(x), '%Y-%m-%d %H:%M:%S')
 t0, t1 = (P(st), P(en))
 out = {'id': w.get('id')}
 dist = _km(w.get('distance'))
 if dist:
  out['dist'] = round(dist, 3)
 cad = num(w.get('stepCadence'))
 elev = num(w.get('elevationUp'))
 if cad:
  out['cad'] = round(cad)
 if elev is not None:
  out['elev'] = round(elev)
 hrs = []
 for r in w.get('heartRateData') or []:
  v = num(r.get('Avg'))
  if v and r.get('date'):
   hrs.append([round((P(r['date']) - t0).total_seconds() / 60, 1), round(v)])
 if hrs:
  out['hrs'] = hrs
 spd = []
 for r in w.get('walkingAndRunningDistance') or w.get('cyclingDistance') or []:
  v = num(r.get('qty'))
  u = (r.get('units') or 'km').lower()
  if v is None or not r.get('date'):
   continue
  km = v / 1000 if u == 'm' else v * 1.609344 if u.startswith('mi') else v
  spd.append([round((P(r['date']) - t0).total_seconds() / 60, 1), round(km * 60, 2)])
 if spd:
  out['spd'] = spd
 for sp in w.get('splits') or []:
  td = sp.get('targetDistance') or {}
  if (td.get('units') or '').lower() != 'km' or num(td.get('qty')) != 1:
   continue
  laps = []
  for it in sp.get('items') or []:
   m = it.get('metrics') or {}
   d_km = _km(m.get('distance')) if isinstance(m.get('distance'), dict) and (m['distance'].get('units') or '').lower() in ('m', 'km', 'mi') else None
   if d_km is None and m.get('distance'):
    d_km = num(m['distance']) / 1000
   laps.append({'i': it.get('index'), 'pace': round(num(m.get('paceKilometre')) or 0), 'hr': round(num(m.get('heartRateAverage')) or 0), 'hrmax': round(num(m.get('heartRateMaximum')) or 0), 'kcal': round(num(m.get('activeEnergy')) or 0), 'km': round(d_km or 0, 3), 'partial': bool(it.get('isPartial'))})
  if laps:
   out['splits'] = laps
 rec = w.get('heartRateRecovery') or []
 if rec:
  pts = [((P(r['date']) - t1).total_seconds(), num(r.get('Avg'))) for r in rec if r.get('date') and num(r.get('Avg'))]
  if pts:
   h0 = pts[0][1]
   h60 = [v for s_, v in pts if s_ >= 60]
   if h60:
    out['hrr1'] = round(h0 - h60[0])
   out['hr_end'] = round(h0)
 return out

def convert(payload):
 d = payload.get('data', payload)
 rows, workouts = ([], [])
 for m in d.get('metrics', []) or []:
  name = (m.get('name') or '').lower()
  units = (m.get('units') or '').lower()
  data = m.get('data') or []
  if name == 'blood_pressure':
   for r in data:
    t = ts(r.get('date'))
    if r.get('systolic') is not None:
     rows.append(['BloodPressureSystolic', 'G Band', t, t, str(num(r['systolic']))])
    if r.get('diastolic') is not None:
     rows.append(['BloodPressureDiastolic', 'G Band', t, t, str(num(r['diastolic']))])
   continue
  if name == 'sleep_analysis':
   for r in data:
    if r.get('value') is not None and (r.get('startDate') or r.get('start')):
     v = SLEEP_VAL.get(str(r['value']).lower().replace('asleep', '').strip() or 'asleep', 'AsleepUnspecified')
     s0 = r.get('source') or ''
     sl_src = 'G Band' if 'G Band' in s0 else src(s0) if s0 else 'Apple Watch (HAE)'
     rows.append(['SleepAnalysis', sl_src, ts(r.get('startDate') or r.get('start')), ts(r.get('endDate') or r.get('end')), 'HKCategoryValueSleepAnalysis' + v])
    elif r.get('sleepStart'):
     from datetime import datetime, timedelta
     st = datetime.strptime(ts(r['sleepStart']), '%Y-%m-%d %H:%M:%S')
     agg_src = 'G Band (HAE agg)' if 'G Band' in (r.get('source') or '') else 'Apple Watch (HAE agg)'
     staged = sum((num(r.get(k)) or 0 for k in ('core', 'deep', 'rem'))) > 0
     parts = (('core', 'AsleepCore'), ('deep', 'AsleepDeep'), ('rem', 'AsleepREM'), ('awake', 'Awake')) if staged else (('asleep', 'AsleepUnspecified'), ('awake', 'Awake'))
     for k, v in parts:
      h = num(r.get(k)) or 0
      if h <= 0:
       continue
      en = st + timedelta(hours=h)
      rows.append(['SleepAnalysis', agg_src, st.strftime('%Y-%m-%d %H:%M:%S'), en.strftime('%Y-%m-%d %H:%M:%S'), 'HKCategoryValueSleepAnalysis' + v])
      st = en
   continue
  t = MAP.get(name)
  if not t:
   continue
  for r in data:
   v = num(r.get('Avg')) if r.get('Avg') is not None else num(r.get('qty'))
   if v is None:
    continue
   if t in ('ActiveEnergyBurned', 'BasalEnergyBurned') and units == 'kj':
    v /= 4.184
   if t == 'OxygenSaturation' and v > 1.5:
    v /= 100
   if t == 'BloodGlucose' and 'mg' in units:
    v /= 18.016
   if t == 'BodyTemperature' and 'f' in units and ('deg' in units) and (v > 50):
    v = (v - 32) / 1.8
   if t == 'DistanceWalkingRunning' and units in ('mi', 'mile'):
    v *= 1.609
   if t == 'BodyMass' and units == 'lb':
    v *= 0.4536
   st = ts(r.get('date') or r.get('startDate'))
   en = ts(r.get('endDate')) or st
   rows.append([t, src(r.get('source'), t), st, en, str(round(v, 4))])
 for w in d.get('workouts', []) or []:
  st, en = (ts(w.get('start')), ts(w.get('end')))
  if not st:
   continue
  dur = num(w.get('duration')) or 0
  dur = dur / 60 if dur > 400 else dur
  kcal = num(w.get('activeEnergyBurned')) or num(w.get('activeEnergy')) or 0
  if isinstance(w.get('activeEnergyBurned'), dict) and (w['activeEnergyBurned'].get('units') or '').lower() == 'kj':
   kcal /= 4.184
  hr = w.get('heartRate') or {}
  avg = num(w.get('avgHeartRate')) or num(hr.get('avg')) or 0
  mx = num(w.get('maxHeartRate')) or num(hr.get('max')) or 0
  wo = {'type': re.sub('[^A-Za-z]', '', w.get('name') or 'Other') or 'Other', 'dur': dur, 'src': 'HAE', 'start': st, 'end': en, 'ActiveEnergyBurned_sum': kcal, 'HeartRate_average': avg, 'HeartRate_maximum': mx}
  try:
   wo.update(wdetail(w, st, en))
  except Exception:
   pass
  workouts.append(wo)
 return (rows, workouts)

def merge(state, rows, workouts, keep_days=200):
 from collections import defaultdict
 detailed = [(r[2], r[3]) for r in state['rows'] if r[0] == 'SleepAnalysis' and 'agg' not in r[1]]

 def has_detail(a, b):
  return any((s < b and e > a for s, e in detailed))
 agg = [r for r in rows if r[0] == 'SleepAnalysis' and 'agg' in r[1]]
 nights = defaultdict(list)
 for r in agg:
  nights[r[2][:10]].append(r)
 drop = set()
 for k, rs in nights.items():
  if has_detail(min((r[2] for r in rs)), max((r[3] for r in rs))):
   drop.update((id(r) for r in rs))
 rows = [r for r in rows if id(r) not in drop]
 win = defaultdict(lambda: [None, None])
 for r in rows:
  w = win[r[0]]
  w[0] = r[2] if w[0] is None or r[2] < w[0] else w[0]
  w[1] = r[3] if w[1] is None or r[3] > w[1] else w[1]
 old = [r for r in state['rows'] if not (r[0] in win and win[r[0]][0] <= r[2] <= win[r[0]][1])]
 allrows = old + rows
 seen = set()
 out = []
 for r in allrows:
  k = tuple(r)
  if k in seen:
   continue
  seen.add(k)
  out.append(r)
 wk = {w['start'][:16]: w for w in state['workouts']}
 for w in workouts:
  k = w['start'][:16]
  if k not in wk or len(w) >= len(wk[k]):
   wk[k] = w
 latest = max((r[2] for r in out if r[2]), default='2000')
 from datetime import datetime, timedelta
 cut = (datetime.strptime(latest[:10], '%Y-%m-%d') - timedelta(days=keep_days)).strftime('%Y-%m-%d')
 keepall = {'VO2Max', 'BodyMass', 'Height', 'RestingHeartRate', 'HeartRateVariabilitySDNN'}
 out = [r for r in out if r[2] >= cut or r[0] in keepall]
 return {'rows': out, 'workouts': sorted([w for w in wk.values() if w['start'] >= cut], key=lambda w: w['start'])}
