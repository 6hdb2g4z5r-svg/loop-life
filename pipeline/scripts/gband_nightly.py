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
import sys, json, math, statistics as st, subprocess, datetime as dt

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


def fetch(headers, days):
    cmd = ['curl', '-sS', '-m', '120', '-w', '\n%{http_code}']
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


def masd(v):
    if len(v) < 3:
        return None
    return st.mean(abs(v[i + 1] - v[i]) * 10 for i in range(len(v) - 1))


def first(lst):
    return lst[0] if lst and lst[0] not in BAD else None


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


def nightly(data):
    blocks = blocks_utc(data)
    sleeps = {}
    for day in data:
        lab = day.get('timezone') or 0
        for s in day.get('sleeps') or []:
            # epoch was built from the band's local clock minus the label offset: undo it, apply the real band clock
            t0 = dt.datetime.utcfromtimestamp(s['sleepTime'] + lab * 60)
            t0 -= dt.timedelta(minutes=clock_at(t0))
            t1 = t0 + dt.timedelta(seconds=s['wakeTime'] - s['sleepTime'])
            sleeps[t0] = (t0, t1, s)
    out = {}
    for t0, t1, s in sorted(sleeps.values(), key=lambda x: x[2].get('sleepDuration') or 0):
        inn = [b for t, b in blocks if t0 <= t < t1]
        hv = [v for v in (rmssd(rr(b)) for b in inn) if v is not None]
        ha = [v for v in (masd(rr(b)) for b in inn) if v is not None]
        hr = sorted(x for x in (first(b.get('ppgs')) for b in inn) if x)
        rs = [x for x in (first(b.get('resRates')) for b in inn) if x]
        ox = [x for x in (first(b.get('oxygens')) for b in inn) if x]
        tp = [b['temperature']['body'] for b in inn if (b.get('temperature') or {}).get('body')]
        key = (t0 + dt.timedelta(hours=6)).date().isoformat()  # same rule as the dashboard: sleep starting 18:00 UTC onward counts for the next day
        if key in out and (out[key].get('asleep') or 0) >= (s.get('sleepDuration') or 0):
            continue  # keep the main sleep of the night, not a nap
        out[key] = {
            'start': t0.strftime('%Y-%m-%d %H:%M'), 'end': t1.strftime('%Y-%m-%d %H:%M'),
            'asleep': s.get('sleepDuration'), 'deep': s.get('deepDuration'), 'light': s.get('lightDuration'),
            'line': s.get('sleepLine') or '', 'step': s.get('onePointDuration') or 60, 'sci': s.get('accurateType') == 1,
            'hrv': round(st.median(hv), 1) if len(hv) >= 8 else None,
            'hrv_app': round(st.mean(ha), 1) if ha else None,
            'hrv_n': len(hv),
            'rhr': hr[len(hr) // 10] if len(hr) >= 6 else None,
            'resp': round(st.mean(rs), 1) if rs else None,
            'spo2': round(st.mean(ox), 1) if ox else None,
            'temp': round(st.mean(tp), 2) if tp else None,
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
        if 'start' in v:  # a fresh read of the night replaces the stored one entirely
            for a in [a for a in p if a not in ('steps', 'dist')]:
                del p[a]
        p.update(v)
    json.dump(dict(sorted(prev.items())), open(sys.argv[2], 'w'), indent=1)
    for k, v in res.items():
        print(k, 'HRV', v.get('hrv'), 'ms (n', v.get('hrv_n'), ') RHR', v.get('rhr'), 'resp', v.get('resp'), 'steps', v.get('steps'))
