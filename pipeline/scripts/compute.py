import json, sys, math, collections, statistics as st
from datetime import datetime, timedelta, date
raw = json.load(open(sys.argv[1]))
OUT = sys.argv[2]
rows = raw['rows']
import os as _os
# G Band nightly HRV (RMSSD) read from the G-Band cloud by gband_nightly.py; preferred over Apple Watch SDNN when present
try:
 GB = json.load(open(_os.path.join(_os.path.dirname(_os.path.abspath(sys.argv[1])), 'gband.json')))
except Exception:
 GB = {}
# G Band cloud series (per-minute heart rate, 5-min calories / distance) and its sleep stages, injected as 'G Band' rows:
# the Watch stays preferred minute by minute where it was worn (workouts), the band fills everything else.
try:
 GS = json.load(open(_os.path.join(_os.path.dirname(_os.path.abspath(sys.argv[1])), 'gband_series.json')))
except Exception:
 GS = {}
from datetime import datetime as _D, timedelta as _T
_add = []
for _d, _s in GS.items():
 for _m, _v in enumerate(_s.get('hr') or []):
  if _v:
   _t = f'{_d} {_m // 60:02d}:{_m % 60:02d}:00'
   _add.append(['HeartRate', 'G Band', _t, _t, str(_v)])
 for _f, _type in (('cal', 'ActiveEnergyBurned'), ('dist', 'DistanceWalkingRunning')):
  for _i, _v in enumerate(_s.get(_f) or []):
   if _v:
    _t = f'{_d} {_i * 5 // 60:02d}:{_i * 5 % 60:02d}:00'
    _add.append([_type, 'G Band', _t, _t, str(_v)])
_STAGE = {'0': 'AsleepDeep', '1': 'AsleepCore', '2': 'AsleepREM', '3': 'Awake', '4': 'Awake'}
_gb_nights = [(_k, _g) for _k, _g in GB.items() if _g.get('start') and _g.get('line')]
if _gb_nights:  # the band's own nights replace the sparse G Band sleep copied through Apple Health
 rows = [r for r in rows if not (r[0] == 'SleepAnalysis' and 'G Band' in r[1])]
for _k, _g in _gb_nights:
 _t0 = _D.strptime(_g['start'], '%Y-%m-%d %H:%M')
 _step = _T(seconds=_g.get('step') or 60)
 _i = 0
 _ln = _g['line']
 while _i < len(_ln):
  _j = _i
  while _j < len(_ln) and _ln[_j] == _ln[_i]:
   _j += 1
  _st = _STAGE.get(_ln[_i])
  if _st:
   _add.append(['SleepAnalysis', 'G Band', (_t0 + _step * _i).strftime('%Y-%m-%d %H:%M:%S'), (_t0 + _step * _j).strftime('%Y-%m-%d %H:%M:%S'), 'HKCategoryValueSleepAnalysis' + _st])
  _i = _j
rows = rows + _add
workouts = raw['workouts']
P = lambda s: datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
DOB = date(1994, 2, 10)
HEIGHT = 1.64
TODAY = max((r[2] for r in rows if r[0] == 'HeartRate'))[:10]
TD = datetime.strptime(TODAY, '%Y-%m-%d').date()
CHRONO = (TD - DOB).days / 365.25
NDAYS = 120
days = [(TD - timedelta(days=i)).isoformat() for i in range(NDAYS - 1, -1, -1)]
by = collections.defaultdict(list)
for t, s, sd, ed, v in rows:
 by[t].append((s, sd, ed, v))
isW = lambda s: 'Apple' in s and 'Watch' in s
isG = lambda s: s == 'G Band'
hr = {}
hro = {}
for s, sd, ed, v in by['HeartRate']:
 if sd[:10] < days[0] and sd[:10] < '2026-01-01':
  continue
 k = sd[:16]
 (hr if isW(s) else hro).setdefault(k, []).append(float(v))
oth = sorted(((k, sum(v) / len(v)) for k, v in hro.items() if k not in hr and 35 <= sum(v) / len(v) <= 210))
for j, (k, v) in enumerate(oth):
 win = sorted((x[1] for x in oth[max(0, j - 2):j + 3]))
 med = win[len(win) // 2]
 if abs(v - med) <= 25:
  hr[k] = [med]
hrs = sorted(((P(k + ':00'), sum(v) / len(v)) for k, v in hr.items()))
hr_by_day = collections.defaultdict(list)
for t, v in hrs:
 hr_by_day[t.date().isoformat()].append((t, v))

def hr_between(a, b):
 import bisect
 keys = [x[0] for x in hrs]
 i = bisect.bisect_left(keys, a)
 j = bisect.bisect_right(keys, b)
 return hrs[i:j]
HKEYS = [x[0] for x in hrs]
import bisect

def hr_rng(a, b):
 return hrs[bisect.bisect_left(HKEYS, a):bisect.bisect_right(HKEYS, b)]
stage_map = {'AsleepCore': 'light', 'AsleepDeep': 'deep', 'AsleepREM': 'rem', 'Awake': 'awake', 'AsleepUnspecified': 'light'}
SLEEP_MODE = 'detail_first'

def sleep_group(s):
 if 'G Band' in s:
  return 'gband'
 return 'watch' if isW(s) else 'other:' + s
segs_by = collections.defaultdict(list)
for s, sd, ed, v in by['SleepAnalysis']:
 st_ = v.replace('HKCategoryValueSleepAnalysis', '')
 if st_ not in stage_map:
  continue
 segs_by[sleep_group(s)].append((P(sd), P(ed), stage_map[st_]))
for k in segs_by:
 segs_by[k].sort()

def main_block(segs, d):
 D = datetime.strptime(d, '%Y-%m-%d')
 a, b = (D - timedelta(hours=6), D + timedelta(hours=14))
 ss = [x for x in segs if a <= x[0] < b]
 if not ss:
  return None
 blocks, cur = ([], [ss[0]])
 for x in ss[1:]:
  if (x[0] - cur[-1][1]).total_seconds() > 5400:
   blocks.append(cur)
   cur = [x]
  else:
   cur.append(x)
 blocks.append(cur)

 def covered(bl):
  tot, last = (0, None)
  for x in sorted((y for y in bl if y[2] != 'awake')):
   a0 = x[0] if last is None else max(x[0], last)
   if x[1] > a0:
    tot += (x[1] - a0).total_seconds()
   last = x[1] if last is None else max(last, x[1])
  return tot
 blk = max(blocks, key=covered)
 return (blk, covered(blk))
sleep = {}
sleep_src = {}
for d in days:
 cands = {g: main_block(sg, d) for g, sg in segs_by.items()}
 cands = {g: c for g, c in cands.items() if c and c[1] >= 90 * 60}
 if not cands:
  continue
 longest = max((c[1] for c in cands.values()))
 if SLEEP_MODE == 'gband_only':
  if 'gband' not in cands:
   continue
  pick = 'gband'
 elif 'gband' in cands and _gb_nights:
  pick = 'gband'
 elif 'watch' in cands and cands['watch'][1] >= 0.75 * longest:
  pick = 'watch'
 elif 'gband' in cands:
  pick = 'gband'
 else:
  pick = max(cands, key=lambda g: cands[g][1])
 sleep_src[d] = pick
 ss = cands[pick][0]
 if not ss:
  continue
 blocks, cur = ([], [ss[0]])
 for x in ss[1:]:
  if (x[0] - cur[-1][1]).total_seconds() > 5400:
   blocks.append(cur)
   cur = [x]
  else:
   cur.append(x)
 blocks.append(cur)
 blk = max(blocks, key=lambda bl: sum(((x[1] - x[0]).total_seconds() for x in bl if x[2] != 'awake')))
 tot = collections.Counter()
 last = None
 for x in blk:
  a0 = x[0] if last is None else max(x[0], last)
  if x[1] > a0:
   tot[x[2]] += (x[1] - a0).total_seconds() / 60
  last = x[1] if last is None else max(last, x[1])
 asleep = tot['light'] + tot['deep'] + tot['rem']
 if asleep < 90:
  continue
 start, end = (blk[0][0], max((x[1] for x in blk)))
 span = (end - start).total_seconds() / 60
 sleep[d] = dict(start=start, end=end, asleep=asleep, inbed=span, light=tot['light'], deep=tot['deep'], rem=tot['rem'], awake=max(0, span - asleep), hyp=[(x[0].strftime('%H:%M'), round((x[1] - x[0]).total_seconds() / 60, 1), x[2]) for x in blk])

def daily_sum(t, pick='max'):
 per = collections.defaultdict(lambda: collections.defaultdict(float))
 for s, sd, ed, v in by[t]:
  per[sd[:10]][s] += float(v)
 return {d: max(v.values()) for d, v in per.items()}
steps = daily_sum('StepCount')
# steps: the G Band's own daily count from the G-Band cloud when present (the band is worn all day, the Watch is not)
steps_src = {}
for _d, _g in GB.items():
 if _g.get('steps') is not None:
  steps[_d] = _g['steps']
  steps_src[_d] = 'gband'
active = {d: v for d, v in daily_sum('ActiveEnergyBurned').items()}
basal = daily_sum('BasalEnergyBurned')
dist = daily_sum('DistanceWalkingRunning')
rhr_w = {}
for s, sd, ed, v in by['RestingHeartRate']:
 if isW(s):
  rhr_w[sd[:10]] = float(v)
vo2 = sorted(((sd[:10], float(v)) for s, sd, ed, v in by['VO2Max']))
hrv_all = sorted(((P(sd), float(v)) for s, sd, ed, v in by['HeartRateVariabilitySDNN']))
resp = sorted(((P(sd), float(v)) for s, sd, ed, v in by['RespiratoryRate']))
weights = sorted(((sd[:10], float(v)) for s, sd, ed, v in by['BodyMass']))

def mean(x):
 return sum(x) / len(x) if x else None

def clip(x, a, b):
 return max(a, min(b, x))

def gseries(t, scale=1):
 return sorted(((sd[:16], round(float(v) * scale, 2)) for s, sd, ed, v in by[t] if isG(s)))
g_spo2 = gseries('OxygenSaturation', 100)
g_sys = gseries('BloodPressureSystolic')
g_dia = gseries('BloodPressureDiastolic')
g_temp = gseries('BodyTemperature')
g_glu = gseries('BloodGlucose')
g_hr = gseries('HeartRate')
age = CHRONO
hrmax = max(208 - 0.7 * age, max((w.get('HeartRate_maximum', 0) for w in workouts), default=0))

def wk_out(w, full):
 o = dict(type=w['type'], start=w['start'][11:16], end=w['end'][11:16], dur=round(w['dur']), kcal=round(w.get('ActiveEnergyBurned_sum', 0)), avg=round(w.get('HeartRate_average', 0)), max=round(w.get('HeartRate_maximum', 0)))
 for k in ('id', 'dist', 'cad', 'elev', 'hrr1', 'hr_end'):
  if w.get(k) is not None:
   o[k] = w[k]
 if w.get('dist'):
  o['secs'] = round((P(w['end']) - P(w['start'])).total_seconds())
 if full:
  for k in ('splits', 'hrs', 'spd'):
   if w.get(k):
    o[k] = w[k]
 return o
RUNS = {'Running', 'OutdoorRun', 'IndoorRun'}

def run_vo2(w, rb):
 if w['type'] not in RUNS or not w.get('dist') or w['dist'] < 3 or (w['dur'] < 15):
  return None
 secs = (P(w['end']) - P(w['start'])).total_seconds()
 grade = (w.get('elev') or 0) / (w['dist'] * 1000) / 2
 cost = lambda pace: 3.5 + 0.2 * (60000 / pace) + 0.9 * (60000 / pace) * grade
 pts = []
 sp = [l for l in w.get('splits') or [] if not l.get('partial') and l.get('pace') and l.get('hr')]
 if len(sp) >= 4:
  pts = [(l['pace'], l['hr']) for l in sp[1:max(2, (len(sp) + 1) // 2)]]
 if not pts:
  pts = [(secs / w['dist'], w.get('HeartRate_average') or 0)]
 est = []
 for pace, h in pts:
  f = (h - rb) / (hrmax - rb)
  if 0.55 <= f <= 0.97:
   est.append((cost(pace) - 3.5) / f + 3.5)
 return round(sum(est) / len(est), 1) if est else None
vo2run = []
out_days = {}
rhr_hist, hrv_hist, resp_hist, asleep_hist = ([], [], [], [])
gb_hist = []
gbr_hist, gbp_hist = ([], [])
gbt_hist, gbs_hist, gbm_hist, ill_prev = ([], [], [], 0)
prev_strain = None
for i, d in enumerate(days):
 D = datetime.strptime(d, '%Y-%m-%d')
 sl = sleep.get(d)
 rhr = rhr_w.get(d)
 if sl:
  night = [v for t, v in hr_rng(sl['start'], sl['end'])]
  if night and rhr is None:
   night.sort()
   rhr = mean(night[:max(1, len(night) // 10)])
 else:
  night = []
 hv = [v for t, v in hrv_all if sl and sl['start'] <= t <= sl['end']]
 hrv = mean(hv)
 rr = [v for t, v in resp if sl and sl['start'] <= t <= sl['end']]
 rr = mean(rr) if rr else mean([v for t, v in resp if D - timedelta(hours=12) <= t <= D + timedelta(hours=12)])
 g = GB.get(d) or {}
 hsrc = 'watch' if hrv is not None else None
 if g.get('hrv'):
  hrv, hsrc = g['hrv'], 'gband'
 # band nights: resting heart rate and respiratory rate from the band too, each against its own baseline
 rsrc = 'other'
 if g.get('rhr') and sleep_src.get(d) == 'gband':
  rhr, rsrc = g['rhr'], 'gband'
 psrc = 'other'
 if g.get('resp'):
  rr, psrc = g['resp'], 'gband'

 def base(h):
  h = [x for x in h[-30:] if x is not None]
  if len(h) < 4:
   return (None, None)
  m = mean(h)
  sd = st.pstdev(h) or 1
  return (m, sd)
 bR, sR = base(gbr_hist if rsrc == 'gband' else rhr_hist)
 bH, sH = base(gb_hist if hsrc == 'gband' else hrv_hist)
 bP, sP = base(gbp_hist if psrc == 'gband' else resp_hist)
 recent = [x for x in asleep_hist[-3:] if x is not None]
 debt = sum((max(0, 460 - x) for x in recent)) / max(1, len(recent)) * 0.5 if recent else 0
 need = 460 + debt + (prev_strain or 0) * 2.5
 spf = None
 sd_ = {}
 if sl:
  hvn = clip(sl['asleep'] / need * 100, 0, 100)
  eff = clip(sl['asleep'] / sl['inbed'] * 100, 0, 100)
  prior = [sleep[x] for x in days[max(0, i - 4):i] if x in sleep]
  if prior:

   def mins(t, ref):
    return (t - ref).total_seconds() / 60
   diffs = []
   for p in prior:
    ds = abs(((sl['start'] - p['start']).total_seconds() / 60 + 720) % 1440 - 720)
    de = abs(((sl['end'] - p['end']).total_seconds() / 60 + 720) % 1440 - 720)
    diffs.append((ds + de) / 2)
   cons = clip(100 - mean(diffs) * 0.45, 0, 100)
  else:
   cons = 75
  base_sleep_hr = bR or (rhr or 60)
  stress_frac = sum((1 for v in night if v > base_sleep_hr * 1.2)) / len(night) * 100 if night else 0
  if sleep_src.get(d) == 'gband':  # the band barely detects awakenings: efficiency is left out of its score
   spf = round(clip((0.55 * hvn + 0.2 * cons + 0.05 * (100 - stress_frac)) / 0.8, 0, 100))
  else:
   spf = round(clip(0.55 * hvn + 0.2 * cons + 0.2 * eff + 0.05 * (100 - stress_frac), 0, 100))
  sd_ = dict(hvn=round(hvn), cons=round(cons), eff=round(eff), stress=round(stress_frac), restor=round((sl['deep'] + sl['rem']) / sl['asleep'] * 100))
 rec = None
 if hrv is not None or rhr is not None:
  c = 0
  w = 0
  if hrv is not None and bH:
   c += 0.5 * clip((hrv - bH) / sH, -3, 3)
   w += 0.5
  if rhr is not None and bR:
   c += 0.25 * clip(-(rhr - bR) / sR, -3, 3)
   w += 0.25
  if rr is not None and bP:
   c += 0.05 * clip(-(rr - bP) / sP, -3, 3)
   w += 0.05
  if spf is not None:
   c += 0.2 * clip((spf - 75) / 15, -3, 3)
   w += 0.2
  if w >= 0.45:
   rec = round(clip(58 + 38 * math.tanh(0.75 * c / w), 1, 99))
 rb = bR or rhr or 60
 hrr = hrmax - rb
 samp = hr_by_day.get(d, [])
 zones = [0.0] * 6
 trimp = 0
 for j, (t, v) in enumerate(samp):
  dt = (samp[j + 1][0] - t).total_seconds() / 60 if j + 1 < len(samp) else 1
  dt = min(dt, 5)
  p = (v - rb) / hrr
  z = 0 if p < 0.5 else 1 if p < 0.6 else 2 if p < 0.7 else 3 if p < 0.8 else 4 if p < 0.9 else 5
  zones[z] += dt
  wgt = [0.0, 1, 2, 3, 4, 5][z] if z else 0.25 if p > 0.3 else 0.04
  trimp += dt * wgt
 strain = round(21 * (1 - math.exp(-trimp / 200)), 1) if samp else None
 wk_today = [w for w in workouts if w['start'][:10] == d]

 def in_wk(t):
  return any((P(w['start']) - timedelta(minutes=5) <= t <= P(w['end']) + timedelta(minutes=15) for w in wk_today))
 hourly = [[] for _ in range(24)]
 for t, v in samp:
  if sl and sl['start'] <= t <= sl['end']:
   continue
  if in_wk(t):
   continue
  s = clip((v - rb - 8) / 40 * 3, 0, 3)
  hourly[t.hour].append(s)
 stress_h = [round(mean(h), 2) if h else None for h in hourly]
 sv = [x for x in stress_h if x is not None]
 stress_avg = round(mean(sv), 1) if sv else None
 hr5 = collections.defaultdict(list)
 for t, v in samp:
  hr5[t.hour * 12 + t.minute // 5].append(v)
 out_days[d] = dict(rec=rec, hrvSrc=hsrc, stepsSrc=steps_src.get(d, 'watch'), hrv=round(hrv, 1) if hrv else None, rhr=round(rhr) if rhr else None, resp=round(rr, 1) if rr else None, bH=round(bH, 1) if bH else None, bR=round(bR, 1) if bR else None, bP=round(bP, 1) if bP else None, sleep=spf, sleepD=sd_, need=round(need), strain=strain, zones=[round(z) for z in zones], steps=round(steps.get(d, 0)), active=round(active.get(d, 0)), cal=round(active.get(d, 0) + basal.get(d, 0)), dist=round(dist.get(d, 0), 2), stressH=stress_h, stress=stress_avg, workouts=[dict(wk_out(w, i >= NDAYS - 35), **{'vo2e': e} if (e := run_vo2(w, rb)) else {}) for w in wk_today])
 # ---- Health monitor / illness signal: tonight vs your own normal (prior 30 nights, at least 7) ----
 tN, sN = g.get('temp'), g.get('spo2')
 def _b(hh):
  v = [x for x in hh[-30:] if x is not None]
  return (mean(v), st.pstdev(v) or 0.01) if len(v) >= 7 else (None, None)
 bT, sT = _b(gbt_hist); bS, sS = _b(gbs_hist)
 bR7, sR7 = _b(gbr_hist if rsrc == 'gband' else rhr_hist)
 bH7, sH7 = _b(gb_hist if hsrc == 'gband' else hrv_hist)
 bP7, sP7 = _b(gbp_hist if psrc == 'gband' else resp_hist)
 mon = []
 if rhr is not None and bR7:
  mon.append(['rhr', round(rhr), round(bR7, 1), rhr - bR7 <= max(3, 1.5 * sR7), 'up'])
 if hrv is not None and bH7:
  mon.append(['hrv', round(hrv), round(bH7, 1), hrv >= bH7 - max(0.15 * bH7, 1.5 * sH7), 'down'])
 if rr is not None and bP7:
  mon.append(['resp', round(rr, 1), round(bP7, 1), rr - bP7 <= max(1.0, 1.5 * sP7), 'up'])
 if tN is not None and bT:
  mon.append(['temp', round(tN, 2), round(bT, 2), tN - bT <= max(0.4, 1.5 * sT), 'up'])
 if sN is not None and bS:
  mon.append(['spo2', round(sN, 1), round(bS, 1), sN >= min(bS - max(1.5, 2 * sS), 95) and sN >= 93, 'down'])
 n_out = sum(1 for m in mon if not m[3])
 lvl = 2 if n_out >= 3 or (n_out >= 2 and ill_prev >= 2) else 1 if n_out >= 2 else 0
 out_days[d]['ill'] = dict(level=lvl, out=n_out, n=len(mon), m=mon) if mon else None
 ill_prev = n_out if mon else 0
 for x in out_days[d]['workouts']:
  if x.get('vo2e'):
   vo2run.append((d, x['vo2e']))
 if sl:
  out_days[d]['sl'] = dict(start=sl['start'].strftime('%H:%M'), end=sl['end'].strftime('%H:%M'), asleep=round(sl['asleep']), inbed=round(sl['inbed']), light=round(sl['light']), deep=round(sl['deep']), rem=round(sl['rem']), awake=round(sl['awake']), hyp=sl['hyp'], src=sleep_src.get(d, '').replace('other:', ''))
 if out_days[d].get('sl') and out_days[d]['sl'].get('src') == 'gband' and g.get('start'):
  # how far to trust tonight's numbers: scientific sleep = per-minute stages incl. REM and tighter HRV
  out_days[d]['sl']['sci'] = bool(g.get('sci'))
  if g.get('spo2') is not None:
   out_days[d]['sl']['ox'] = dict(avg=g['spo2'], min=g.get('spo2_min'), odi=g.get('odi'), lo=g.get('ox90'), n=g.get('ox_n'))
 out_days[d]['conf'] = dict(
  stages='measured' if (out_days[d].get('sl') or {}).get('src') != 'gband' else ('good' if g.get('sci') else 'estimate'),
  hrv=None if hrv is None else ('±2 ms' if hsrc == 'gband' and g.get('sci') else '±5 ms' if hsrc == 'gband' else 'watch'))
 if g.get('moves') is not None and out_days[d].get('sl'):
  out_days[d]['sl']['moves'] = g['moves']
  mvb = [x for x in gbm_hist[-30:] if x is not None]
  out_days[d]['sl']['movesB'] = round(mean(mvb), 1) if len(mvb) >= 3 else None
 gbt_hist.append(tN); gbs_hist.append(sN); gbm_hist.append(g.get('moves'))
 if i >= NDAYS - 35:
  out_days[d]['hr5'] = [round(mean(hr5[k])) if hr5.get(k) else None for k in range(288)]
 rhr_hist.append(rhr if rsrc != 'gband' else None)
 gbr_hist.append(rhr if rsrc == 'gband' else None)
 hrv_hist.append(hrv if hsrc == 'watch' else None)
 gb_hist.append(hrv if hsrc == 'gband' else None)
 resp_hist.append(rr if psrc != 'gband' else None)
 gbp_hist.append(rr if psrc == 'gband' else None)
 asleep_hist.append(sl['asleep'] if sl else None)
 prev_strain = strain
STRENGTH = {'TraditionalStrengthTraining', 'FunctionalStrengthTraining', 'HighIntensityIntervalTraining', 'CrossTraining'}

def healthspan(end_idx, window=30):
 ds = days[max(0, end_idx - window + 1):end_idx + 1]
 dd = [out_days[x] for x in ds]
 wk = window / 7
 h_sleep = mean([x['sl']['asleep'] / 60 for x in dd if 'sl' in x])
 cons = mean([x['sleepD']['cons'] for x in dd if x.get('sleepD')])
 z13 = sum((sum(x['zones'][1:4]) for x in dd)) / wk
 z45 = sum((sum(x['zones'][4:6]) for x in dd)) / wk
 strength = sum((w['dur'] for x in dd for w in x['workouts'] if w['type'] in STRENGTH)) / wk
 stp = mean([x['steps'] for x in dd if x['steps'] > 500])
 rh = mean([x['rhr'] for x in dd if x['rhr']])
 endd = ds[-1]
 lo = (datetime.strptime(endd, '%Y-%m-%d') - timedelta(days=42)).strftime('%Y-%m-%d')
 vr = [val for dt, val in vo2run if lo <= dt <= endd][-3:]
 v = mean(vr) if vr else mean([val for dt, val in vo2 if dt <= endd][-3:])
 wt = [val for dt, val in weights if dt <= endd]
 bmi = wt[-1] / HEIGHT ** 2 if wt else None
 m = {}
 if h_sleep:
  m['sleep_hours'] = (h_sleep, clip(abs(h_sleep - 7.75) * 1.1 - 0.6, -0.8, 3))
 if cons:
  m['sleep_consistency'] = (cons, clip((78 - cons) * 0.06, -1.2, 2))
 m['zones_13'] = (z13, clip(1.2 - min(z13, 360) / 150 * 1.0, -1.2, 1.2))
 m['zones_45'] = (z45, clip(0.8 - min(z45, 120) / 45 * 0.6, -0.8, 0.8))
 m['strength'] = (strength, clip(0.9 - min(strength, 150) / 60 * 0.7, -0.9, 0.9))
 if stp:
  m['steps'] = (stp, clip(-(stp - 7500) / 2500 * 0.8, -2, 3))
 if v:
  m['vo2max'] = (v, clip(-(v - 42) * 0.35, -5, 6))
 if rh:
  m['rhr'] = (rh, clip((rh - 64) * 0.14, -3, 4))
 if bmi:
  m['bmi'] = (bmi, clip((abs(bmi - 22.5) - 1.5) * 0.3, -0.5, 3))
 agev = CHRONO + sum((x[1] for x in m.values()))
 return (round(agev, 1), {k: (round(a, 1), round(b, 2)) for k, (a, b) in m.items()})
hs_hist = []
for k in range(NDAYS - 1, 29, -7):
 a, _ = healthspan(k)
 hs_hist.append((days[k], a))
hs_hist.reverse()
age_now, metrics_now = healthspan(NDAYS - 1)
age_prev, _ = healthspan(NDAYS - 31)
pace = round(clip(1 + (age_now - age_prev) * 0.5, -1, 3), 2)
streak = 0
for d in reversed(days):
 if out_days[d].get('sl') or out_days[d]['strain']:
  streak += 1
 else:
  break

def lastof(pred):
 v = [r[3] or r[2] for r in rows if pred(r)]
 return max(v)[:16] if v else None
# ---- Personal patterns: what moved YOUR recovery, from your own history (needs >= 5 days on each side) ----
# local clock offset (minutes) from a UTC date onward; extend when moving time zone
LOCAL = [('2000-01-01', 60), ('2026-10-24', 480)]
def _loc(dd):
 off = 0
 for since, m in LOCAL:
  if dd >= since:
   off = m
 return off
def _hm(x):
 return int(x[:2]) * 60 + int(x[3:5])
def _feat(d, i):
 t = out_days.get(d) or {}
 sl = t.get('sl') or {}
 pd = days[i - 1] if i else None
 p = out_days.get(pd) or {}
 f = {}
 if sl.get('asleep'):
  f['short'] = sl['asleep'] < 390 if sl['asleep'] < 390 or sl['asleep'] >= 450 else None
  bt = (_hm(sl['start']) + _loc(d)) % 1440
  bt = bt + 1440 if bt < 720 else bt  # minutes after previous midnight, 24:00 = 1440
  f['_bt'] = bt
 if p.get('strain') is not None:
  f['hard'] = p['strain'] >= 14 if p['strain'] >= 14 or p['strain'] < 10 else None
 if p:
  ends = [(_hm(w['end']) + _loc(pd)) % 1440 for w in p.get('workouts') or []]
  f['late'] = any(e >= 20 * 60 or e < 3 * 60 for e in ends) if ends else False
 if p.get('steps') is not None:
  f['active'] = p['steps'] >= 10000 if p['steps'] >= 10000 or p['steps'] < 6000 else None
 return f
_rows = []
for i, d in enumerate(days):
 t = out_days.get(d) or {}
 if t.get('rec') is None:
  continue
 _rows.append((d, t['rec'], t.get('hrv'), _feat(d, i)))
_rows = _rows[-90:]
_bts = sorted(r[3]['_bt'] for r in _rows if '_bt' in r[3])
if _bts:
 _mbt = _bts[len(_bts) // 2]
 for r in _rows:
  if '_bt' in r[3]:
   r[3]['late_bed'] = True if r[3]['_bt'] >= _mbt + 45 else False if r[3]['_bt'] <= _mbt + 10 else None
PAT_TXT = {
 'short': ('Sleeping under 6.5 h', 'Dormir moins de 6 h 30', 'vs 7.5 h or more', 'vs 7 h 30 ou plus'),
 'late_bed': ('Going to bed 45+ min later than usual', 'Se coucher 45 min+ plus tard que d’habitude', 'vs your usual time', 'vs votre heure habituelle'),
 'hard': ('A hard day the day before (strain 14+)', 'Une grosse journée la veille (effort 14+)', 'vs strain under 10', 'vs effort sous 10'),
# evening training is already measured by the app Journal ("Evening workout", auto from workouts)
 'active': ('10,000+ steps the day before', '10 000+ pas la veille', 'vs under 6,000', 'vs moins de 6 000'),
}
patterns = []
for k, (en, fr, en2, fr2) in PAT_TXT.items():
 yes = [r for r in _rows if r[3].get(k) is True]
 no = [r for r in _rows if r[3].get(k) is False]
 if len(yes) < 5 or len(no) < 5:
  continue
 dr = mean([r[1] for r in yes]) - mean([r[1] for r in no])
 # recovery only: raw HRV mixes Watch SDNN and band RMSSD eras, recovery is already scored against each source's own baseline
 patterns.append(dict(k=k, en=en, fr=fr, en2=en2, fr2=fr2, rec=round(dr), eff='clear' if abs(dr) >= 5 else 'mild' if abs(dr) >= 3 else 'none', n=len(yes), m=len(no)))
patterns.sort(key=lambda x: -abs(x['rec']))
# ---- Today's plan, in local clock time (each past night read in the time zone it was slept in) ----
def _plan():
 t = out_days.get(TODAY) or {}
 wk = []
 for k in days[-8:-1]:
  sl = (out_days.get(k) or {}).get('sl')
  if sl and sl.get('asleep', 0) >= 300:
   wk.append((_hm(sl['end']) + _loc(k)) % 1440)
 if not wk or not t.get('need'):
  return None
 wk.sort()
 wake = wk[len(wk) // 2]
 bed = (wake - t['need'] - 15) % 1440
 f = lambda x: '%02d:%02d' % (x % 1440 // 60, x % 60)
 r = t.get('rec')
 lo, hi = (8, 12) if r is None else (max(0, 6 + r / 99 * 11 - 1.5), min(21, 6 + r / 99 * 11 + 1.5))
 if r is not None and r < 34:  # red: active recovery only, same band as the app's day banner
  lo, hi = 3, 8
 il = (t.get('ill') or {}).get('level', 0)
 if il >= 1:
  hi = min(hi, 10 if il == 1 else 7); lo = min(lo, hi - 3)
 return dict(wake=f(wake), bed=f(bed), caffeine=f(bed - 480), meal=f(bed - 180), strain=[round(max(0, lo), 1), round(hi, 1)], ill=il)
plan = _plan()
sync = dict(watch_hr=lastof(lambda r: r[0] == 'HeartRate' and isW(r[1])), hr_any=lastof(lambda r: r[0] == 'HeartRate'), gband=lastof(lambda r: isG(r[1])), sleep=lastof(lambda r: r[0] == 'SleepAnalysis'), steps=lastof(lambda r: r[0] == 'StepCount'), workout=max((w['start'] for w in workouts), default=None), log=raw.get('meta', {}).get('log', []))
import datetime as _dt
data = dict(built=_dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M'), sync=sync, today=TODAY, chrono=round(CHRONO, 1), hrmax=round(hrmax), days=out_days, order=days, healthspan=dict(age=age_now, prev=age_prev, pace=pace, metrics=metrics_now, hist=hs_hist), vo2=vo2[-30:], vo2run=vo2run[-30:], streak=streak, patterns=patterns, local=_loc(TODAY), plan=plan, gband=dict(spo2=g_spo2, sys=g_sys, dia=g_dia, temp=g_temp, glu=g_glu, hr=g_hr))
json.dump(data, open(OUT, 'w'), separators=(',', ':'))
t = out_days[TODAY]
y = out_days[days[-2]]
print('today', TODAY, {k: t[k] for k in ('rec', 'hrv', 'rhr', 'resp', 'sleep', 'strain', 'steps', 'stress', 'need')}, t.get('sleepD'))
for d in days[-10:]:
 x = out_days[d]
 print(d, x['rec'], x['sleep'], x['strain'], x['hrv'], x['rhr'], x.get('sl', {}).get('asleep'), x['steps'], x['zones'], x['stress'])
print('nights with sleep', sum((1 for d in days if 'sl' in out_days[d])), '/', NDAYS)
print('age', age_now, age_prev, pace, metrics_now)
