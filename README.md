# DevEriik IPTV Checker

Simple IPTV checker designed for Termux / Pydroid3.

Features:
- Parses combos: `user:pass`, `user:pass:host`, `user:pass@host` and M3U URLs.
- Concurrent checking using ThreadPoolExecutor.
- Auto-installs `requirements.txt` when run in environments without `requests`.

Usage:

```bash
# install python in termux or pydroid3, then:
python3 DevEriik.py --input combos.txt --threads 20 --timeout 8 --server http://example.com:8080
```

The script will attempt to run `pip install -r requirements.txt` if `requests` is missing.
