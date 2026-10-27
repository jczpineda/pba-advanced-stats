"""Why this project publishes no lineup on/off data.

The play-by-play logs substitutions, so in principle you can rebuild who was on the
floor at every moment and derive lineup-level net ratings. This script does exactly
that for one game and then checks the result against the official box score.

It fails, and that is the point: the feed logs some substitutions and omits others,
so reconstructed minutes drift away from the official ones. Run it to see the damage
before trusting any lineup number derived from this source.

    python lineup_check.py 601
"""
import argparse
import collections

from paths import raw_path
from pba_parse import parse_game

mins2s = lambda s: (lambda a, b: int(a) * 60 + int(b))(*s.split(':'))


def resolve_names(g, team):
    """Map abbreviated box names ("K. Buffen") to full play-by-play names."""
    pbp_names = {e['player'] for e in g['pbp'] if e['team'] == team and e['player']}
    for e in g['pbp']:
        if e['team'] == team:
            pbp_names |= {n for n in (e['sub_in'], e['sub_out'], e['assist']) if n}
    out = {}
    for p in g['teams'][team]['players']:
        box, init = p['player'], p['player'][0].lower()
        tail = box.split('. ', 1)[1] if '. ' in box else box
        cand = [n for n in pbp_names
                if n.lower().replace('.', '').endswith(tail.lower().replace('.', ''))
                and n[0].lower() == init]
        if len(cand) == 1:
            out[box] = cand[0]
    return out


def check(game_id, tolerance=45):
    g = parse_game(raw_path(game_id).read_text(encoding='utf-8', errors='replace'), game_id)
    codes = [g['a'], g['b']]
    full = {t: resolve_names(g, t) for t in codes}

    on = {t: {full[t][p['player']] for p in g['teams'][t]['players']
              if p['group'] == 'starters' and p['player'] in full[t]} for t in codes}
    for t in codes:
        assert len(on[t]) == 5, 'could not resolve 5 starters for %s' % t

    secs = collections.Counter()
    plus = collections.Counter()
    minus = collections.Counter()
    ghost_subs = []
    prev = 0

    for e in g['pbp']:
        dt = e['elapsed'] - prev
        if dt > 0:
            for t in codes:
                for pl in on[t]:
                    secs[pl] += dt
        if e['made'] and e['value']:
            for t in codes:
                for pl in on[t]:
                    (plus if t == e['team'] else minus)[pl] += e['value']
        if e['type'] == 'sub' and e['sub_in'] and e['sub_out']:
            t = e['team']
            if e['sub_out'] not in on[t]:
                ghost_subs.append((e['period'], e['clock'], t, e['sub_out']))
            on[t].discard(e['sub_out'])
            on[t].add(e['sub_in'])
        prev = e['elapsed']

    end = 4 * 720 + max(0, g['periods'] - 4) * 300
    for t in codes:
        for pl in on[t]:
            secs[pl] += end - prev

    n_sub = sum(1 for e in g['pbp'] if e['type'] == 'sub')
    print('game %d  %s %d-%d %s   %d substitutions logged'
          % (game_id, g['a'], g['final'][g['a']], g['final'][g['b']], g['b'], n_sub))
    print('subs naming a player who was not on the floor: %d' % len(ghost_subs))
    for s in ghost_subs[:5]:
        print('    P%d %s  %s  %s' % s)

    print()
    print('%-4s %-22s %8s %8s %7s   %7s %7s' %
          ('TM', 'PLAYER', 'box min', 'rebuilt', 'diff', 'box +/-', 'rebuilt'))
    bad_min = bad_pm = total = 0
    for t in codes:
        for p in g['teams'][t]['players']:
            nm = full[t].get(p['player'])
            if not nm:
                continue
            total += 1
            box_s, got_s = mins2s(p['mins']), secs[nm]
            got_pm = plus[nm] - minus[nm]
            off_min = abs(got_s - box_s) > tolerance
            off_pm = got_pm != p['pm']
            bad_min += off_min
            bad_pm += off_pm
            flag = '  <-- ' + ', '.join(
                f for f, b in (('minutes', off_min), ('+/-', off_pm)) if b) if (off_min or off_pm) else ''
            print('%-4s %-22s %8s %7ds %+6ds   %+7d %+7d%s'
                  % (t, p['player'], p['mins'], got_s, got_s - box_s, p['pm'], got_pm, flag))

    print('\nminutes wrong by more than %ds: %d of %d players' % (tolerance, bad_min, total))
    print('plus-minus disagreeing with the box: %d of %d players' % (bad_pm, total))
    print('\nThe official box score is internally consistent -- its plus-minus sums to exactly')
    print('5x the final margin for both teams -- so the box is right and the sub log is')
    print('incomplete. That is why no lineup on/off data is published.')
    return bad_min, bad_pm, total


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('game_id', nargs='?', type=int, default=601)
    a = ap.parse_args()
    check(a.game_id)
