#!/usr/bin/env bash
# Loop Life refresh, GitHub Actions version.
# Wraps the unchanged pipeline scripts (pipeline/scripts/*.py, dayplan.js):
#   receiver template + inbox -> refresh.py -> dash.json -> receiver "dash" -> Telegram cards.
# Needs env: RECEIVER_URL RECEIVER_KEY TG_TOKEN TG_CHAT (GitHub Actions secrets).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
W="${RUNNER_TEMP:-/tmp}/looplife"
rm -rf "$W" && mkdir -p "$W/scripts"
cp "$HERE"/scripts/*.py "$HERE"/scripts/*.js "$W/scripts/"
cd "$W"
umask 077
printf '%s\n%s\n' "$RECEIVER_URL" "$RECEIVER_KEY" > receiver.txt
printf '%s\n%s\n' "$TG_TOKEN" "$TG_CHAT" > tg.txt

rx() { curl -sSL --max-time 120 "$RECEIVER_URL?key=$RECEIVER_KEY&$1"; }
post() { curl -sSL --max-time 300 -H 'Content-Type: text/plain' --data-binary "@$2" "$RECEIVER_URL?key=$RECEIVER_KEY&store=$1"; }

# 1. page template (kept on the receiver; refreshed whenever the dashboard design changes)
for i in 1 2 3 4 5; do rx 'action=state&name=template' > template.html; grep -q '/\*DATA\*/' template.html && break; sleep 15; done
[ "$(grep -c '/\*DATA\*/' template.html)" = 1 ] || { echo "template missing on receiver"; exit 1; }

# 2. previous dashboard (for Telegram "what changed" detection)
rx 'action=state&name=dash' > prev_dash.json || true
python3 - <<'PY'
import json
t = open('template.html').read()
try:
    d = open('prev_dash.json').read(); json.loads(d)
    if '"ok":false' in d.replace(' ', '')[:40]: raise ValueError
except Exception:
    d = None
open('prev.html', 'w').write(t.replace('/*DATA*/', d) if d else '')
PY

# 3. refresh (unchanged script)
out="$(python3 -I scripts/refresh.py "$W" 2>&1 || { sleep 30; python3 -I scripts/refresh.py "$W" 2>&1; })"
echo "$out" | tail -12
n="$(echo "$out" | sed -n 's/^inbox files: \([0-9]*\).*/\1/p' | head -1)"
echo "$out" | grep -q '^OK rows added' || { echo "refresh failed"; exit 1; }

# 4. publish the new dashboard data to the receiver (the iPhone app reads "dash")
if [ "${n:-0}" != 0 ] || [ ! -s prev.html ]; then
  echo "dash stored: $(post dash dash.json)"
fi

# 5. Notifications (iPhone push once subscribed, else Telegram)
python3 "$HERE/notify.py" --ensure-vapid || true
python3 - <<'PY'
import json, subprocess, os, datetime as dt
U, K = open('receiver.txt').read().split()
def blob(name):
    try:
        r = subprocess.run(['curl', '-sSL', '--max-time', '60', f'{U}?key={K}&action=state&name={name}'], capture_output=True, text=True).stdout
        j = json.loads(r); return j.get('docs', {}) if isinstance(j, dict) else {}
    except Exception:
        return {}
today = dt.datetime.now(dt.timezone.utc).date().isoformat()
json.dump({'rec': blob('db_recai').get(today) or {}, 'prof': blob('db_settings').get('profile') or {}}, open('plan.json', 'w'))
PY
if [ "${n:-0}" = 0 ]; then
  [ -s prev.html ] && python3 "$HERE/notify.py" tg_notify.py prev.html - tg.txt --empty || true
elif [ -s prev.html ]; then
  python3 "$HERE/notify.py" tg_notify.py prev.html dash.json tg.txt plan.json || echo "telegram step failed"
fi
python3 "$HERE/coach.py" dash.json || echo "coach step failed"
python3 -c "import json,datetime as d;D=json.load(open('dash.json'));t=d.datetime.utcnow().date().isoformat();x=D['days'].get(t,{});print('today',t,'rec',x.get('rec'),'sleep',x.get('sleep'),'strain',x.get('strain'))" || true
rm -f receiver.txt tg.txt
