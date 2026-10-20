"""Loop Life notification router.

Runs the unchanged tg_notify.py / tg_remind.py scripts, but routes their messages:
  - to iPhone web push (Loop Life app) once at least one device is subscribed,
  - otherwise to Telegram (unchanged behaviour).
Routine "Synchro HH:MM" progress notes are dropped (exports now arrive many times a day).

Usage (inside the work dir that holds receiver.txt and tg.txt):
  python3 notify.py --ensure-vapid
  python3 notify.py tg_notify.py <args...>
  python3 notify.py tg_remind.py <args...>
Env: NOTIFY_CHANNEL = auto (default) | push | telegram | both
"""
import base64, html, json, os, re, runpy, subprocess, sys, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, 'scripts')
APP_URL = 'https://6hdb2g4z5r-svg.github.io/loop-life/'
URL, KEY = open('receiver.txt').read().split()


def rx_get_raw(name, tries=3):
    """Returns (value, status): status is 'ok', 'missing' (the receiver explicitly has no such blob) or 'error'
    (outage, non-JSON answer, timeout). Callers must never treat 'error' as 'missing'."""
    import time
    q = urllib.parse.urlencode({'key': KEY, 'action': 'state', 'name': name})
    for i in range(tries):
        r = subprocess.run(['curl', '-sSL', '--max-time', '60', f'{URL}?{q}'], capture_output=True, text=True).stdout
        try:
            j = json.loads(r)
        except Exception:
            j = None
        if isinstance(j, dict) and j.get('ok') is False:
            return (None, 'missing') if j.get('error') == 'missing' else (None, 'error')
        if j is not None:
            return j, 'ok'
        if i + 1 < tries:
            time.sleep(5 * (i + 1))
    return None, 'error'


def rx_get(name):
    return rx_get_raw(name)[0]


def rx_put(name, obj):
    q = urllib.parse.urlencode({'key': KEY, 'store': name})
    r = subprocess.run(['curl', '-sSL', '--max-time', '60', '-H', 'Content-Type: text/plain', '--data-binary', json.dumps(obj), f'{URL}?{q}'],
                       capture_output=True, text=True).stdout
    r = r.replace(' ', '')
    return '"ok":true' in r and '"stored"' in r


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b'=').decode()


def ensure_vapid():
    """Create the push key pair once and keep it on the receiver (private never leaves receiver/Actions).
    The pair is generated ONLY when the receiver explicitly says it has none: a receiver outage (HTML error
    page, empty answer) must never regenerate it, because every phone subscription is bound to the public key
    and a new pair silently breaks all of them (that is what happened on 2026-10-20, 'VapidPkHashMismatch')."""
    v, status = rx_get_raw('vapid')
    if status == 'ok' and isinstance(v, dict) and v.get('pem'):
        return v
    if status != 'missing':
        print('vapid: receiver unreadable, keeping the existing key pair')
        return None
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    k = ec.generate_private_key(ec.SECP256R1())
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    pub = b64u(k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    v = {'pem': pem, 'pub': pub}
    if rx_put('vapid', v) and rx_put('vapid_pub', {'key': pub}):
        print('vapid: created')
        return v
    print('vapid: could not be stored, not using the unsaved pair')
    return None


def to_push(caption):
    lines = [l for l in caption.split('\n') if l.strip()]
    lines = [l for l in lines if 'claude.ai/artifact' not in l and '<a href' not in l]
    plain = [html.unescape(re.sub(r'<[^>]+>', '', l)).strip() for l in lines]
    title = plain[0] if plain else 'Loop Life'
    body = '\n'.join(plain[1:])
    if len(body) > 600:
        body = body[:597] + '…'
    return title, body


def get_subs():
    subs = rx_get('push_subs') or {}
    return subs.get('subs', {}) if isinstance(subs, dict) else {}


def push_send(caption):
    title, body = to_push(caption)
    return push_raw(title, body)


def push_raw(title, body):
    subs = get_subs()
    if not subs:
        return None
    from pywebpush import webpush, WebPushException
    from py_vapid import Vapid01
    v = ensure_vapid()
    if not v:
        print('push: no usable key pair right now, skipped ·', title)
        return False
    vapid = Vapid01.from_pem(v['pem'].encode())
    payload = json.dumps({'title': title, 'body': body, 'url': APP_URL, 'tag': re.sub(r'\W+', '-', title.split('·')[0].strip().lower())[:40]})
    ok, dead = 0, []
    for ep, sub in subs.items():
        # a device that subscribed with another public key can never receive anything from this pair: drop it,
        # the app re-subscribes itself with the current key the next time it is opened
        if sub.get('vapidPub') and sub['vapidPub'] != v['pub']:
            print('push: subscription made with an old key, removed')
            dead.append(ep)
            continue
        try:
            webpush(subscription_info={'endpoint': sub['endpoint'], 'keys': sub['keys']}, data=payload, vapid_private_key=vapid,
                    vapid_claims={'sub': 'mailto:6hdb2g4z5r-svg@users.noreply.github.com'}, ttl=6 * 3600)
            ok += 1
        except WebPushException as e:
            code = getattr(e.response, 'status_code', None)
            msg = str(e)[:160]
            print('push failed', code, msg)
            if code in (404, 410) or (code in (400, 403) and 'Vapid' in str(e)):
                dead.append(ep)
        except Exception as e:
            print('push error', str(e)[:160])
    if dead:
        cur = rx_get('push_subs') or {'subs': {}}
        for ep in dead:
            cur.get('subs', {}).pop(ep, None)
        rx_put('push_subs', cur)
        print('push: removed', len(dead), 'dead subscription(s)')
    print(f'push: sent to {ok}/{len(subs)} device(s) · {title}')
    return ok > 0


def main():
    if sys.argv[1] == '--ensure-vapid':
        ensure_vapid()
        return
    channel = os.environ.get('NOTIFY_CHANNEL', 'auto')
    if channel == 'auto' and get_subs():
        print('notify: iPhone notifications active, Telegram script skipped (coach.py handles push)')
        return
    sys.path.insert(0, SCRIPTS)
    import tg_cards
    orig = tg_cards.tg_send

    def routed(tgfile, caption, photo=None, dry=False):
        if dry:
            return orig(tgfile, caption, photo, dry)
        if re.match(r'\s*<b>Synchro \d', caption) and 'aucune nouvelle' not in caption:
            print('notify: routine sync note skipped')
            return True
        pushed = None
        if channel in ('auto', 'push', 'both'):
            try:
                pushed = push_send(caption)
            except Exception as e:
                print('push error:', str(e)[:200])
        if channel in ('telegram', 'both') or (channel == 'auto' and not pushed):
            return orig(tgfile, caption, photo, dry)
        return bool(pushed)

    tg_cards.tg_send = routed
    script = os.path.join(SCRIPTS, sys.argv[1])
    sys.argv = [script] + sys.argv[2:]
    runpy.run_path(script, run_name='__main__')


if __name__ == '__main__':
    main()
