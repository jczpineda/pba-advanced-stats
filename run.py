#!/usr/bin/env python3
"""Run the whole pipeline: fetch -> parse -> validate -> metrics -> dashboard.

    python run.py              # build everything (uses cached pages if present)
    python run.py --fetch      # also fetch any missing games from the feed
    python run.py --smoke      # fetch only 3 games per conference, for a quick check
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--fetch', action='store_true',
                    help='download missing game pages (1 req/sec; cached pages are skipped)')
    ap.add_argument('--smoke', action='store_true',
                    help='only the first 3 games per conference')
    a = ap.parse_args()

    import fetch
    from paths import CONFERENCES, RAW

    if a.fetch or a.smoke:
        print('== fetching ==')
        for c in CONFERENCES:
            fetch.fetch_conference(c, limit=3 if a.smoke else None)

    have = len(list(RAW.glob('*.html')))
    if not have:
        sys.exit('No game pages in data/raw. Run:  python run.py --fetch')
    print('== building from %d cached pages ==' % have)

    import build_dashboard
    build_dashboard.main()
    print('\nOpen dist/dashboard.html in a browser.')


if __name__ == '__main__':
    main()
