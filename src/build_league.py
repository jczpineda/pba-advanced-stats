"""Parse every scraped game into a per-conference season dataset.

Every game must pass three independent checks before it enters the dataset:
the score rebuilt from scoring events must match the scorelines printed in the
page, that rebuild must match the official quarter table, and the box score must
sum to the final. A game that fails any of them is skipped, never patched.
"""
import collections
import json

from paths import CONFERENCES, DERIVED, ids_for, raw_path
from pba_parse import parse_game

ma = lambda s: tuple(int(x) for x in s.split('-'))
mins2f = lambda s: (lambda a, b: int(a) + int(b)/60.0)(*s.split(':'))

# box-score keys we sum into season totals
CNT = ('pts', 'off', 'def', 'reb', 'ast', 'to', 'stl', 'blk', 'pf', 'fls_on')
SPL = (('fg', 'fgm', 'fga'), ('p3', 'p3m', 'p3a'), ('p4', 'p4m', 'p4a'), ('ft', 'ftm', 'fta'))


def blank():
    d = {k: 0 for k in CNT}
    for _, m, a in SPL: d[m] = d[a] = 0
    d['min'] = 0.0; d['g'] = 0; d['gs'] = 0; d['pm'] = 0
    return d


def add(dst, src_player):
    p = src_player
    for k in CNT: dst[k] += p[k]
    for key, m, a in SPL:
        x, y = ma(p[key]); dst[m] += x; dst[a] += y
    dst['min'] += mins2f(p['mins'])
    dst['pm'] += p['pm']
    dst['g'] += 1
    if p['group'] == 'starters': dst['gs'] += 1


def build(which):
    label = CONFERENCES[which]['label']
    ids = ids_for(which)
    games, skipped, ot = [], [], 0
    players = collections.defaultdict(blank)     # (team, name) -> totals
    pname  = {}
    teams  = collections.defaultdict(blank)      # team -> own totals
    opps   = collections.defaultdict(blank)      # team -> what opponents did
    rec    = collections.defaultdict(lambda: {'w': 0, 'l': 0, 'pf': 0, 'pa': 0,
                                              'g': 0, 'mp': 0.0, 'periods': 0})

    for gid in ids:
        path = raw_path(gid)
        if not path.exists():
            skipped.append((gid, 'not fetched')); continue
        g = parse_game(path.read_text(encoding='utf-8', errors='replace'), gid)
        if not g:
            skipped.append((gid, 'no box score')); continue
        c = g['checks']
        if not (c['pbp_final_ok'] and c['box_sum_ok'] and c['anchor_bad'] == 0):
            skipped.append((gid, 'failed checks %s' % c)); continue
        if g['periods'] > 4: ot += 1
        a, b = g['a'], g['b']
        tmmp = 5 * (48 + 5 * (g['periods'] - 4))      # team minutes incl. overtime

        for side, other in ((a, b), (b, a)):
            T = g['teams'][side]
            for p in T['players']:
                key = (side, p['player'])
                add(players[key], p)
                pname[key] = p['player']
            # team totals summed from the player rows (they reconcile; checked below)
            tt = teams[side]; ot_ = opps[other]
            for p in T['players']:
                add(tt, p); add(ot_, p)
            tt['g'] -= len(T['players']) - 1          # g counted per player; fix to 1
            ot_['g'] -= len(T['players']) - 1
            r = rec[side]
            r['g'] += 1; r['pf'] += g['final'][side]; r['pa'] += g['final'][other]
            r['mp'] += tmmp; r['periods'] += g['periods']
            if g['final'][side] > g['final'][other]: r['w'] += 1
            else: r['l'] += 1

        games.append({'id': gid, 'date': g['datetime'], 'venue': g['venue'],
                      'a': a, 'b': b, 'sa': g['final'][a], 'sb': g['final'][b],
                      'periods': g['periods'],
                      'qa': g['quarters'][a], 'qb': g['quarters'][b],
                      'name_a': g['name_a'], 'name_b': g['name_b']})

    out = {
        'key': which, 'label': label,
        'games': sorted(games, key=lambda x: x['id']),
        'players': [dict(team=k[0], name=k[1], **v) for k, v in sorted(players.items())],
        'teams': {k: dict(v) for k, v in teams.items()},
        'opps':  {k: dict(v) for k, v in opps.items()},
        'rec':   {k: dict(v) for k, v in rec.items()},
        'ot_games': ot, 'skipped': skipped,
    }
    return out


if __name__ == '__main__':
    import sys
    for which in (sys.argv[1:] or list(CONFERENCES)):
        d = build(which)
        out_path = DERIVED / ('season_%s.json' % which)
        json.dump(d, open(out_path, 'w', encoding='utf-8'),
                  separators=(',', ':'), ensure_ascii=False)
        nt = len(d['teams'])
        print('%-5s %-20s games=%3d  teams=%2d  players=%3d  OT games=%d  skipped=%d'
              % (which, d['label'], len(d['games']), nt, len(d['players']),
                 d['ot_games'], len(d['skipped'])))
        if d['skipped']: print('       skipped:', d['skipped'][:6])
        # reconcile: team points from player rows vs sum of game finals
        for t, tt in sorted(d['teams'].items()):
            r = d['rec'][t]
            assert tt['pts'] == r['pf'], (t, tt['pts'], r['pf'])
        print('       team points reconcile with game finals for all %d teams' % nt)
        tot_g = sum(r['g'] for r in d['rec'].values())
        print('       team-games %d (= 2 x %d games)  record check %s'
              % (tot_g, len(d['games']), 'OK' if tot_g == 2*len(d['games']) else 'BAD'))
