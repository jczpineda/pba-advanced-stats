"""Project paths, so every script runs the same from any working directory."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
RAW = DATA / 'raw'            # scraped game pages (gitignored; ~98 MB)
IDS = DATA / 'ids'            # one file of game ids per conference
DERIVED = DATA / 'derived'    # season_*.json, league.json
DIST = ROOT / 'dist'          # the built dashboard
TEMPLATE = ROOT / 'template' / 'dashboard.html'

for _p in (RAW, IDS, DERIVED, DIST):
    _p.mkdir(parents=True, exist_ok=True)

CONFERENCES = {
    'gov':  {'label': "Governors' Cup",     'slug': 'pba-50th-season-governors-cup'},
    'comm': {'label': "Commissioner's Cup", 'slug': 'pba-50th-season-commissioner-s-cup'},
}


def raw_path(game_id):
    return RAW / ('%d.html' % game_id)


def ids_for(conf):
    f = IDS / ('%s_ids.txt' % conf)
    return [int(x) for x in f.read_text().split()] if f.exists() else []
