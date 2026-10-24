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

Usage:  python3 -I gband_nightly.py HEADERS_JSON OUT_JSON [DAYS]
HEADERS_JSON holds {"Authorization": "token ...", "User-Agent": ..., ...}.
Exit code 3 = token rejected (needs refresh), 2 = other fetch error.
"""
import sys, json, math, statistics as st, subprocess, datetime as dt

API = 'https://cn.vpgband.com/api/v1/healthData/getDataListWithLimitLength?day={}'
BAD = (0, 255)


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


def nightly(data):
    blocks = []  # (utc datetime, block)
    for day in data:
        base = dt.datetime.fromisoformat(day['date']) - dt.timedelta(hours=day.get('timezone') or 0)
        for b in day.get('origDatas') or []:
            blocks.append((base + dt.timedelta(minutes=b['time']), b))
    blocks.sort(key=lambda t: t[0])
    sleeps = {}
    for day in data:
        for s in day.get('sleeps') or []:
            sleeps[s['sleepTime']] = s
    out = {}
    for s in sleeps.values():
        t0 = dt.datetime.utcfromtimestamp(s['sleepTime'])
        t1 = dt.datetime.utcfromtimestamp(s['wakeTime'])
        inn = [b for t, b in blocks if t0 <= t < t1]
        hv = [v for v in (rmssd(rr(b)) for b in inn) if v is not None]
        ha = [v for v in (masd(rr(b)) for b in inn) if v is not None]
        hr = sorted(x for x in (first(b.get('ppgs')) for b in inn) if x)
        rs = [x for x in (first(b.get('resRates')) for b in inn) if x]
        ox = [x for x in (first(b.get('oxygens')) for b in inn) if x]
        tp = [b['temperature']['body'] for b in inn if (b.get('temperature') or {}).get('body')]
        key = t1.date().isoformat()  # a night belongs to the day you wake up
        out[key] = {
            'start': t0.strftime('%Y-%m-%d %H:%M'), 'end': t1.strftime('%Y-%m-%d %H:%M'),
            'asleep': s.get('sleepDuration'), 'deep': s.get('deepDuration'), 'light': s.get('lightDuration'),
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
    res = nightly(fetch(headers, days))
    prev = {}
    try:
        prev = json.load(open(sys.argv[2]))
    except Exception:
        pass
    for k, v in res.items():
        prev.setdefault(k, {}).update(v)
    json.dump(dict(sorted(prev.items())), open(sys.argv[2], 'w'), indent=1)
    for k, v in res.items():
        print(k, 'HRV', v.get('hrv'), 'ms (n', v.get('hrv_n'), ') RHR', v.get('rhr'), 'resp', v.get('resp'), 'steps', v.get('steps'))
