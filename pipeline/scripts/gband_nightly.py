"""G Band -> nightly recovery metrics for Loop Life.

Reads the G-Band cloud (read-only, same request the G Band app makes after login)
and computes, for each night, over the G-Band sleep window:
  hrv      RMSSD in ms (median of the ~10-min readings), comparable to WHOOP/Oura
  hrv_app  the G Band app's own value (mean absolute successive difference, ms)
  rhr      resting heart rate (10th percentile of 5-min HR during sleep)
  resp     respiratory rate (breaths/min, mean)
  spo2     blood oxygen (%, mean)
  temp     body temperature (deg C, mean)
  sleep    asleep / deep / light minutes, start and end (UTC)
and, for each calendar day, the band's step count and distance (steps, dist km).

Usage:  python3 -I gband_nightly.py HEADERS_JSON OUT_JSON [DAYS] [SERIES_JSON]
HEADERS_JSON holds {"Authorization": "token ...", "User-Agent": ..., ...}.
Exit code 3 = token rejected (needs refresh), 2 = other fetch error.
"""
import sys, os, json, math, statistics as st, subprocess, datetime as dt

API = 'https://cn.vpgband.com/api/v1/healthData/getDataListWithLimitLength?day={}'
BAD = (0, 255)
# The server labels each day with the phone's current UTC offset in MINUTES ("timezone": 480 = UTC+8), even for data
# the band recorded earlier on its old clock. CLOCK lists the band clock's offset (minutes) from a UTC instant onward;
# block times and the server's sleep epochs are converted with it. Extend it when travelling (band clock follows the phone).
CLOCK = [('2000-01-01 00:00', 0), ('2026-10-25 04:00', 480)]


def clock_at(local_naive):
    off = 0
    for since, m in CLOCK:
        if local_naive - dt.timedelta(minutes=m) >= dt.datetime.fromisoformat(since):
            off = m
    return off


def off_utc(t_utc):
    """Offset (minutes) of the user's local clock at a UTC instant."""
    off = 0
    for since, m in CLOCK:
        if t_utc >= dt.datetime.fromisoformat(since):
            off = m
    return off


def merge(sleeps, gap_max=60):
    """The band splits one night when you stir (e.g. 18:49-19:44 then 20:00-02:43): join pieces <= gap_max min apart."""
    out = []
    for t0, t1, s in sorted(sleeps, key=lambda x: x[0]):
        if out and 0 <= (t0 - out[-1][1]).total_seconds() / 60 <= gap_max:
            a0, a1, a = out[-1]
            step = a.get('onePointDuration') or 60
            gap = round((t0 - a1).total_seconds() / step)
            m = dict(a)
            m['sleepLine'] = (a.get('sleepLine') or '') + '3' * gap + (s.get('sleepLine') or '')
            for k in ('sleepDuration', 'deepDuration', 'lightDuration'):
                m[k] = (a.get(k) or 0) + (s.get(k) or 0)
            m['accurateType'] = 1 if a.get('accurateType') == 1 and s.get('accurateType') == 1 else 0
            m['pieces'] = a.get('pieces', 1) + 1
            out[-1] = (a0, max(a1, t1), m)
        else:
            out.append((t0, t1, s))
    return out


def fetch(headers, days):
    cmd = ['curl', '-sS', '--compressed', '-m', os.environ.get('GBAND_TIMEOUT', '300'), '-w', '\n%{http_code}']
    for k, v in headers.items():
        cmd += ['-H', f'{k}: {v}']
    cmd.append(API.format(days))
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    body, _, code = out.rpartition('\n')
    if code in ('401', '403'):
        sys.exit(3)
    try:
        d = json.loads(body)
    except Exception:
        print('fetch error', code, body[:200])
        sys.exit(2)
    if d.get('code') != 10000:
        print('api error', d.get('code'), d.get('msg'))
        sys.exit(3 if d.get('code') in (10001, 10002, 401) else 2)
    return d['data']


def rr(b):
    return [x for x in b.get('hrvs') or [] if x not in BAD]


def rmssd(v):
    if len(v) < 3:
        return None
    return math.sqrt(sum(((v[i + 1] - v[i]) * 10) ** 2 for i in range(len(v) - 1)) / (len(v) - 1))


def rmssd_clean(b):
    """RMSSD of one 5-min block after artifact rejection: (ms, share of clean beat pairs) or (None, share).
    Blocks with >= 2 minutes of movement are skipped (motion corrupts wrist PPG). Beats outside 300-2000 ms, or more
    than 20% away from the median of their 11-beat neighbourhood (missed or extra beats), are dropped, and only
    successive pairs of two clean beats count."""
    mv = [x for x in (b.get('sleepActivitys') or []) if x != 255]
    v = [x for x in b.get('hrvs') or [] if x not in BAD and 30 <= x <= 200]
    if 2 <= len(v) < 20:  # without scientific sleep the band keeps only ~4 beats per block: lighter rules
        if sum(mv) > 40:
            return None, 0
        pairs = [(x, y) for x, y in zip(v, v[1:]) if abs(y - x) <= 0.2 * (x + y) / 2]
        if len(pairs) < 2:
            return None, 0
        return math.sqrt(sum(((y - x) * 10) ** 2 for x, y in pairs) / len(pairs)), len(pairs) / (len(v) - 1)
    if sum(1 for x in mv if x > 0) >= 2:
        return None, 0
    if len(v) < 20:
        return None, 0
    ok = [abs(x - st.median(v[max(0, i - 5):i + 6])) <= 0.2 * st.median(v[max(0, i - 5):i + 6]) for i, x in enumerate(v)]
    pairs = [(v[i], v[i + 1]) for i in range(len(v) - 1) if ok[i] and ok[i + 1]]
    q = len(pairs) / max(1, len(b.get('hrvs') or []) - 1)
    if len(pairs) < 25:
        return None, q
    return math.sqrt(sum(((y - x) * 10) ** 2 for x, y in pairs) / len(pairs)), q


def masd(v):
    if len(v) < 3:
        return None
    return st.mean(abs(v[i + 1] - v[i]) * 10 for i in range(len(v) - 1))


def first(lst):
    return lst[0] if lst and lst[0] not in BAD else None


def stages(line, step):
    """Minutes per stage from the band's sleep line (0 deep, 1 light, 2 REM, 3/4 awake), one char per `step` s."""
    k = (step or 60) / 60
    c = {ch: line.count(ch) * k for ch in '01234'}
    return round(c['0']), round(c['1']), round(c['2']), round(c['3'] + c['4'])


def dips(ox, hours):
    """Oxygen desaturation events: runs of readings >= 3 points below the night's median; per hour asleep."""
    if len(ox) < 12 or not hours:
        return None, None
    med = st.median(ox)
    ev, run = 0, False
    for x in ox:
        low = x <= med - 3
        if low and not run:
            ev += 1
        run = low
    return round(ev / hours, 1), sum(1 for x in ox if x < 90)


def blocks_utc(data):
    out = []
    for day in data:
        base = dt.datetime.fromisoformat(day['date'])
        for b in day.get('origDatas') or []:
            loc = base + dt.timedelta(minutes=b['time'])
            out.append((loc - dt.timedelta(minutes=clock_at(loc)), b))
    return sorted(out, key=lambda t: t[0])


def series(data):
    """{utc_date: {'hr': [1440 bpm or 0], 'cal': [288 kcal], 'dist': [288 km]}}"""
    out = {}
    for t, b in blocks_utc(data):
        d = out.setdefault(t.date().isoformat(), {'hr': [0] * 1440, 'cal': [0] * 288, 'dist': [0] * 288})
        m = t.hour * 60 + t.minute
        vals = b.get('ppgs') or []
        multi = sum(1 for x in vals[1:] if x not in BAD) > 0
        for i, x in enumerate(vals if multi else vals[:1]):
            if x not in BAD and 30 <= x <= 220 and m + i < 1440:
                d['hr'][m + i] = int(x)
        if b.get('cal'):
            d['cal'][m // 5] = round(float(b['cal']), 2)
        if b.get('dis'):
            d['dist'][m // 5] = round(float(b['dis']), 3)
    return out


def _bhr(b):
    v = [x for x in (b.get('ppgs') or []) if x not in BAD and 30 <= x <= 200]
    return st.median(v) if v else None


def _bsteps(b):
    s = b.get('step')
    return sum(x for x in s if x not in BAD) if isinstance(s, list) else (s or 0)


def onset_fix(t0, blocks, med, cap=240):
    """The band sometimes starts a night hours after you fell asleep. Walk back from its start, 5 min at a time,
    while the heart rate stays at sleep level (<= the night's median + 4 bpm) with no steps and a still wrist; a single block without
    a reading is skipped, two in a row stop the walk. Returns the corrected start and the minutes added."""
    bt = {t: b for t, b in blocks}
    t = t0 - dt.timedelta(minutes=t0.minute % 5, seconds=t0.second) - dt.timedelta(minutes=5)
    ext, miss, best = 0, 0, t0
    while ext < cap:
        b = bt.get(t)
        h = _bhr(b) if b else None
        mv = [x for x in ((b or {}).get('sleepActivitys') or []) if x != 255]
        if b is not None and (_bsteps(b) > 0 or sum(mv) > 5):
            break  # walking, or the wrist moving: awake
        if h is None:
            miss += 1
            if miss >= 2:
                break
        elif h > med + 4:
            break
        else:
            miss = 0
            best = t
        ext += 5
        t -= dt.timedelta(minutes=5)
    return best, round((t0 - best).total_seconds() / 60)


def nightly(data):
    blocks = blocks_utc(data)
    sleeps, seen = {}, {}
    for day in data:
        lab = day.get('timezone') or 0
        for s in day.get('sleeps') or []:
            # epoch was built from the band's local clock minus the label offset: undo it, apply the real band clock
            t0 = dt.datetime.utcfromtimestamp(s['sleepTime'] + lab * 60)
            t0 -= dt.timedelta(minutes=clock_at(t0))
            t1 = t0 + dt.timedelta(seconds=s['wakeTime'] - s['sleepTime'])
            # around a time-zone change the cloud lists the same sleep under two day labels, hours apart:
            # keep one copy, the one whose label matches the real clock at that instant
            ident = (s['wakeTime'] - s['sleepTime'], s.get('sleepDuration'), s.get('sleepLine'))
            ok = lab == off_utc(t0)
            if ident in seen:
                p0, pok = seen[ident]
                if pok or not ok and p0 <= t0:
                    continue
                sleeps.pop(p0, None)
            seen[ident] = (t0, ok)
            sleeps[t0] = (t0, t1, s)
    out = {}
    for t0, t1, s in sorted(merge(sleeps.values()), key=lambda x: x[2].get('sleepDuration') or 0):
        inn = [b for t, b in blocks if t0 <= t < t1]
        hv0 = [v for v in (rmssd(rr(b)) for b in inn) if v is not None]  # unfiltered, kept for comparison
        hv = [v for v, q in (rmssd_clean(b) for b in inn) if v is not None]
        ha = [v for v in (masd(rr(b)) for b in inn) if v is not None]
        hr = sorted(x for x in (first(b.get('ppgs')) for b in inn) if x)
        rs = [x for x in (first(b.get('resRates')) for b in inn) if x]
        ox = [x for x in (first(b.get('oxygens')) for b in inn) if x]
        tp = [b['temperature']['body'] for b in inn if (b.get('temperature') or {}).get('body')]
        oxa = [x for b in inn for x in (b.get('oxygens') or []) if x not in BAD]
        mv = [x for b in inn for x in (b.get('sleepActivitys') or []) if x != 255]  # movement per minute while asleep
        line, step = s.get('sleepLine') or '', s.get('onePointDuration') or 60
        sci = s.get('accurateType') == 1
        dp, lt, rem, aw = stages(line, step) if line else (None, None, None, None)
        odi, ox90 = dips(oxa, (s.get('sleepDuration') or 0) / 60)
        if (s.get('sleepDuration') or 0) < 45:
            continue  # band taken off and left still (shower, charging): not a sleep
        fix = 0
        if len(hr) >= 6:
            t0n, fix = onset_fix(t0, blocks, hr[len(hr) // 2])
            if fix >= 15:  # extend the night: the added time counts as light sleep
                more = [b for t, b in blocks if t0n <= t < t0]
                s = dict(s, sleepDuration=(s.get('sleepDuration') or 0) + fix, lightDuration=(s.get('lightDuration') or 0) + fix,
                         sleepLine='1' * round(fix * 60 / step) + line)
                line, t0 = s['sleepLine'], t0n
                inn = more + inn
                hv = [v for v, q in (rmssd_clean(b) for b in inn) if v is not None]
                hv0 = [v for v in (rmssd(rr(b)) for b in inn) if v is not None]
                dp, lt, rem, aw = stages(line, step)
            else:
                fix = 0
        # same rule as the dashboard, on the LOCAL clock: a sleep starting 18:00 local or later counts for the next day
        key = (t0 + dt.timedelta(minutes=off_utc(t0) + 360)).date().isoformat()
        if key in out and (out[key].get('asleep') or 0) >= (s.get('sleepDuration') or 0):
            continue  # keep the main sleep of the night, not a nap
        out[key] = {
            'start': t0.strftime('%Y-%m-%d %H:%M'), 'end': t1.strftime('%Y-%m-%d %H:%M'),
            'asleep': s.get('sleepDuration'), 'deep': s.get('deepDuration'), 'light': s.get('lightDuration'),
            'line': line, 'step': step, 'sci': sci,
            'rem': rem if sci else None, 'awake': aw, 'deep_line': dp,
            'odi': odi, 'ox90': ox90, 'ox_n': len(oxa), 'pieces': s.get('pieces', 1), 'onset_fix': fix,
            'hrv': round(st.median(hv), 1) if len(hv) >= 8 else None,
            'hrv_app': round(st.mean(ha), 1) if ha else None,
            'hrv_n': len(hv),
            'hrv_raw': round(st.median(hv0), 1) if len(hv0) >= 8 else None,
            'hrv_q': round(100 * len(hv) / len(inn)) if inn else None,  # % of the night's 5-min blocks usable for HRV
            'rhr': hr[len(hr) // 10] if len(hr) >= 6 else None,
            'resp': round(st.mean(rs), 1) if rs else None,
            'spo2': round(st.mean(ox), 1) if ox else None,
            'temp': round(st.mean(tp), 2) if tp else None,
            'spo2_min': min(oxa) if oxa else None,
            'moves': round(sum(1 for x in mv if x > 0) / (len(mv) / 60), 1) if len(mv) >= 60 else None,  # minutes with movement per hour
        }
    for day in data:
        sp = day.get('sport') or {}
        if sp.get('step') is not None:
            out.setdefault(day['date'], {}).update(steps=int(sp['step']), dist=round(float(sp.get('dis') or 0), 2))
    return dict(sorted(out.items()))


if __name__ == '__main__':
    headers = json.load(open(sys.argv[1]))
    days = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    data = fetch(headers, days)
    if os.environ.get('GBAND_RAW'):  # keep the raw read for offline checks
        json.dump(data, open(os.environ['GBAND_RAW'], 'w'))
    res = nightly(data)
    if len(sys.argv) > 4:  # heart rate / calories / distance series, kept 130 days
        try:
            ser = json.load(open(sys.argv[4]))
            assert isinstance(ser, dict) and 'ok' not in ser
        except Exception:
            ser = {}
        new = series(data)
        for k, v in new.items():
            old = ser.get(k)
            if old:  # keep what an earlier read had where this read has nothing
                for f in ('hr', 'cal', 'dist'):
                    v[f] = [a if a else b for a, b in zip(v[f], old.get(f) or [0] * len(v[f]))]
            ser[k] = v
        keep = sorted(ser)[-130:]
        json.dump({k: ser[k] for k in keep}, open(sys.argv[4], 'w'), separators=(',', ':'))
    prev = {}
    try:
        prev = json.load(open(sys.argv[2]))
    except Exception:
        pass
    for k, v in res.items():
        p = prev.setdefault(k, {})
        if 'start' in v and p.get('start') and p['start'] != v['start'] and (p.get('asleep') or 0) > (v.get('asleep') or 0):
            v = {a: b for a, b in v.items() if a in ('steps', 'dist')}  # never let a shorter sleep replace the stored night
        if 'start' in v:  # a fresh read of the night replaces the stored one entirely
            for a in [a for a in p if a not in ('steps', 'dist')]:
                del p[a]
        p.update(v)
    json.dump(dict(sorted(prev.items())), open(sys.argv[2], 'w'), indent=1)
    for k, v in res.items():
        print(k, 'HRV', v.get('hrv'), 'ms (n', v.get('hrv_n'), ') RHR', v.get('rhr'), 'resp', v.get('resp'), 'steps', v.get('steps'))
