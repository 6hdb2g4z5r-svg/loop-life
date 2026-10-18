#!/usr/bin/env bash
# Loop Life daily reminders (morning plan / midday steps / bedtime planner), GitHub Actions version.
# Same tg_remind.py as before, fed from the receiver instead of the claude.ai artifact.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
W="${RUNNER_TEMP:-/tmp}/llremind"
rm -rf "$W" && mkdir -p "$W" && cd "$W"
umask 077
printf '%s\n%s\n' "$RECEIVER_URL" "$RECEIVER_KEY" > receiver.txt
printf '%s\n%s\n' "$TG_TOKEN" "$TG_CHAT" > tg.txt
python3 - <<'PY'
import json, subprocess, datetime as dt
U, K = open('receiver.txt').read().split()
def get(name):
    r = subprocess.run(['curl', '-sSL', '--max-time', '90', f'{U}?key={K}&action=state&name={name}'], capture_output=True, text=True).stdout
    return r
t, d = get('template'), get('dash')
json.loads(d)
open('page.html', 'w').write(t.replace('/*DATA*/', d))
open('dash.json', 'w').write(d)
def docs(name):
    try:
        j = json.loads(get(name)); return j.get('docs', {}) if isinstance(j, dict) else {}
    except Exception:
        return {}
today = dt.datetime.now(dt.timezone.utc).date()
T = today.isoformat()
wk = docs('db_weekplan'); week = {}
for i in range(7):
    k = (today - dt.timedelta(days=i)).isoformat()
    w = wk.get(k)
    if w and (i == 0 or any(e.get('date') == T for e in w.get('days') or [])):
        week = w; break
plan = {'rec': docs('db_recai').get(T) or {}, 'obj': docs('db_objai').get(T) or {},
        'prof': docs('db_settings').get('profile') or {}, 'week': week}
json.dump(plan, open('plan.json', 'w'))
PY
python3 "$HERE/notify.py" --ensure-vapid || true
python3 "$HERE/notify.py" tg_remind.py page.html tg.txt "${REMIND_MODE:-auto}" plan.json
python3 "$HERE/coach.py" dash.json || echo "coach step failed"
rm -f receiver.txt tg.txt
