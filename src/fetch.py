"""Fetch PBA game pages from the stats frame that pba.ph embeds.

pba.ph/recap is client-rendered, so the recap URL itself carries no statistics.
The data lives in an iframe on a separate host, served as static HTML -- no browser
automation needed.

Polite by construction: one request per second, and a game already on disk is never
re-requested, so re-running the pipeline costs no network at all.
"""
import argparse
import gzip
import sys
import time
import urllib.request

from paths import CONFERENCES, ids_for, raw_path

MIN_BYTES = 50_000          # a valid game page is ~500 KB; anything smaller is an error page
DELAY = 1.0                 # seconds between live requests


def fetch_one(game_id, slug, retries=3, timeout=45):
    """Return (html, from_cache). Cached pages are returned without a request."""
    path = raw_path(game_id)
    if path.exists() and path.stat().st_size > MIN_BYTES:
        return path.read_text(encoding='utf-8', errors='replace'), True

    url = 'https://pba-api01.actech2.com/tournaments/%s?game_id=%d' % (slug, game_id)
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept-Encoding': 'gzip',
        'Referer': 'https://pba.ph/recap?match=%d' % game_id,
    })
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get('Content-Encoding') == 'gzip':
                    raw = gzip.decompress(raw)
                html = raw.decode('utf-8', 'replace')
            path.write_text(html, encoding='utf-8')
            return html, False
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))        # 2s, then 4s


def fetch_conference(conf, limit=None):
    slug = CONFERENCES[conf]['slug']
    ids = ids_for(conf)[:limit]
    if not ids:
        sys.exit('no game ids for %r -- expected data/ids/%s_ids.txt' % (conf, conf))
    hit = miss = 0
    for gid in ids:
        _, cached = fetch_one(gid, slug)
        hit, miss = hit + cached, miss + (not cached)
        if not cached:
            time.sleep(DELAY)
    print('%-5s %-20s %3d games  (%d cached, %d fetched)'
          % (conf, CONFERENCES[conf]['label'], len(ids), hit, miss))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('conferences', nargs='*', default=list(CONFERENCES),
                    choices=list(CONFERENCES) + [[]])
    ap.add_argument('--limit', type=int, help='only the first N games (for a smoke test)')
    a = ap.parse_args()
    for c in (a.conferences or list(CONFERENCES)):
        fetch_conference(c, a.limit)
