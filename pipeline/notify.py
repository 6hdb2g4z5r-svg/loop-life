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


def rx_get(name):
    q = urllib.parse.urlencode({'key': KEY, 'action': 'state', 'name': name})
    r = subprocess.run(['curl', '-sSL', '--max-time', '60', f'{URL}?{q}'], capture_output=True, text=True).stdout
    try:
        j = json.loads(r)
    except Exception:
        return None
    return None if isinstance(j, dict) and j.get('ok') is False else j


def rx_put(name, obj):
    q = urllib.parse.urlencode({'key': KEY, 'store': name})
    r = subprocess.run(['curl', '-sSL', '--max-time', '60', '-H', 'Content-Type: text/plain', '--data-binary', json.dumps(obj), f'{URL}?{q}'],
                       capture_output=True, text=True).stdout
    return '"ok":true' in r.replace(' ', '')


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b'=').decode()


def ensure_vapid():
    """Create the push key pair once and keep it on the receiver (private never leaves receiver/Actions)."""
    v = rx_get('vapid')
    if v and v.get('pem'):
        return v
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    k = ec.generate_private_key(ec.SECP256R1())
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    pub = b64u(k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    v = {'pem': pem, 'pub': pub}
    if rx_put('vapid', v) and rx_put('vapid_pub', {'key': pub}):
        print('vapid: created')
    return v


def to_push(caption):
    lines = [l for l in caption.split('\n') if l.strip()]
    lines = [l for l in lines if 'claude.ai/artifact' not in l and '<a href' not in l]
    plain = [html.unescape(re.sub(r'<[^>]+>', '', l)).strip() for l in lines]
    title = plain[0] if plain else 'Loop Life'
    body = '\n'.join(plain[1:])
    if len(body) > 600:
        body = body[:597] + '…'
    return title, body


def push_send(caption):
    subs = rx_get('push_subs') or {}
    subs = subs.get('subs', {}) if isinstance(subs, dict) else {}
    if not subs:
        return None
    from pywebpush import webpush, WebPushException
    from py_vapid import Vapid01
    v = ensure_vapid()
    vapid = Vapid01.from_pem(v['pem'].encode())
    title, body = to_push(caption)
    payload = json.dumps({'title': title, 'body': body, 'url': APP_URL, 'tag': re.sub(r'\W+', '-', title.split('·')[0].strip().lower())[:40]})
    ok, dead = 0, []
    for ep, sub in subs.items():
        try:
            webpush(subscription_info=sub, data=payload, vapid_private_key=vapid, vapid_claims={'sub': APP_URL}, ttl=6 * 3600)
            ok += 1
        except WebPushException as e:
            code = getattr(e.response, 'status_code', None)
            print('push failed', code, str(e)[:160])
            if code in (404, 410):
                dead.append(ep)
    if dead:
        cur = rx_get('push_subs') or {'subs': {}}
        for ep in dead:
            cur.get('subs', {}).pop(ep, None)
        rx_put('push_subs', cur)
        print('push: removed', len(dead), 'expired subscription(s)')
    print(f'push: sent to {ok}/{len(subs)} device(s) · {title}')
    return ok > 0


def main():
    if sys.argv[1] == '--ensure-vapid':
        ensure_vapid()
        return
    channel = os.environ.get('NOTIFY_CHANNEL', 'auto')
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
