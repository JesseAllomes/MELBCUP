# ruff: noqa
"""Read-only pull of RaceLens: GET-only after login. Usage: python3 -I pull.py ENVFILE OUTDIR"""
import json, sys, urllib.request, urllib.parse, http.cookiejar, pathlib
env = dict(l.split('=', 1) for l in open(sys.argv[1]).read().split('\n') if '=' in l)
base = env['url'].strip().rstrip('/'); out = pathlib.Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
def req(path, body=None):
    r = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                               headers={'Content-Type': 'application/json'}, method='GET' if body is None else 'POST')
    return json.loads(op.open(r, timeout=60).read())
req('/api/login', {'password': env['password'].strip()})
def save(name, obj): (out / name).write_text(json.dumps(obj, indent=1))
for p in ('packs', 'jobs', 'settings', 'sources'):
    save(p + '.json', req('/api/' + p))
packs = json.loads((out / 'packs.json').read_text())
for pk in packs:
    pid = pk['id']; q = urllib.parse.quote(pid, safe='')
    pack = req(f'/api/packs/{q}'); save(f'pack_{pid.replace(":", "_")}.json', pack)
    races = pack.get('races') or pack.get('meeting', {}).get('races') or []
    for r in races:
        n = r.get('raceNumber') or r.get('number')
        if n is None: continue
        try: save(f'race_{pid.replace(":", "_")}_{n}.json', req(f'/api/packs/{q}/races/{n}'))
        except Exception as e: print('race fail', pid, n, e)
    print(pid, len(races))
