"""After a sync requested from the app (receiver blob "sync_req"), tell the phone by web push what changed,
so the result arrives even when the app is in the background.
Usage (in the work dir): python3 syncpush.py prev_dash.json dash.json RUN_START_EPOCH"""
import json, sys, time
import notify as N

LABELS = [('steps', 'pas', lambda v: f'{round(v):,}'.replace(',', ' ')), ('strain', 'effort', lambda v: f'{v:.1f}'), ('sleep', 'sommeil', lambda v: f'{round(v)} %'),
          ('rec', 'récup', lambda v: f'{round(v)} %'), ('cal', 'kcal', lambda v: f'{round(v):,}'.replace(',', ' ')), ('hrv', 'VFC', lambda v: f'{round(v)} ms')]


def changes(prev, cur):
    t = cur.get('today'); a = (prev.get('days') or {}).get(t) or {}; b = (cur.get('days') or {}).get(t) or {}
    out = []
    for k, name, fmt in LABELS:
        if b.get(k) is not None and b.get(k) != a.get(k):
            out.append(f'{fmt(b[k])} {name}' if k in ('steps', 'cal') else f'{name} {fmt(b[k])}')
    return out


def main():
    req, st = N.rx_get_raw('sync_req')
    if st != 'ok' or not isinstance(req, dict) or req.get('done') or not req.get('at'):
        return
    at = req['at'] / 1000
    if time.time() - at > 1200:
        return
    try:
        prev = json.load(open(sys.argv[1]))
    except Exception:
        prev = {}
    ch = changes(prev, json.load(open(sys.argv[2])))
    if ch:
        N.push_raw('Nouvelles données', ' · '.join(ch[:4]))
    elif at > float(sys.argv[3]):
        return  # this run started before the tap: the next run answers
    else:
        N.push_raw('Synchro terminée', 'Pas de nouveaux chiffres du bracelet. Ouvre G Band puis relance.')
    N.rx_put('sync_req', {'done': True, 'at': req['at']})


if __name__ == '__main__':
    main()
