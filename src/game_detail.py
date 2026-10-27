"""Single-game detail: box score, four factors, shot profile, margin timeline.

Built on pba_parse, so it works for any game id in the archive -- not just the one
the dashboard happens to ship with. Replaces the earlier one-off scripts, which had
their own private copy of the parser.
"""
import collections
import re

from pba_parse import parse_game

ma = lambda s: tuple(int(x) for x in s.split('-'))
mins2f = lambda s: (lambda a, b: int(a) + int(b) / 60.0)(*s.split(':'))

WORDS = [('rebound_defensive', 'defensive rebound'),
         ('rebound_offensive', 'offensive rebound'),
         ('jump_shot', 'jumper'), ('free_throw', 'free throw')]
SCORE_FRAG = re.compile(r'\d+ - \d+')


def _tidy(act, player):
    """Display text: drop score fragments and the duplicated leading player name."""
    a = SCORE_FRAG.sub('', act).strip()
    while player and a.startswith(player):
        a = a[len(player):].strip()
    for src, dst in WORDS:
        a = a.replace(src, dst)
    return re.sub(r'\s+', ' ', a.replace('_', ' ')).strip()


def _totals(T):
    """Numeric team totals from the raw box-score strings."""
    fgm, fga = ma(T['fg']); p3m, p3a = ma(T['p3'])
    p4m, p4a = ma(T['p4']); ftm, fta = ma(T['ft'])
    return dict(pts=int(T['pts']), fgm=fgm, fga=fga, p3m=p3m, p3a=p3a,
                p4m=p4m, p4a=p4a, ftm=ftm, fta=fta,
                p2m=fgm - p3m - p4m, p2a=fga - p3a - p4a,
                orb=int(T['off']), drb=int(T['def']), trb=int(T['reb']),
                ast=int(T['ast']), to=int(T['to']), stl=int(T['stl']),
                blk=int(T['blk']), pf=int(T['pf']))


def build(html, game_id, source_url=''):
    g = parse_game(html, game_id)
    if not g:
        raise ValueError('game %s has no completed box score' % game_id)
    c = g['checks']
    if not (c['pbp_final_ok'] and c['box_sum_ok'] and c['anchor_bad'] == 0):
        raise ValueError('game %s failed validation: %s' % (game_id, c))

    A, B = g['a'], g['b']
    codes = [A, B]
    ev = g['pbp']
    nper = g['periods']
    full_time = 4 * 720 + max(0, nper - 4) * 300

    # ---------- play-by-play, display ready ----------
    pbp = []
    for e in ev:
        pbp.append({'period': e['period'], 'clock': e['clock'], 'elapsed': e['elapsed'],
                    'team': e['team'], 'type': e['type'], 'subtype': e['subtype'],
                    'player': e['player'], 'act': _tidy(e['act'], e['player']),
                    'made': e['made'], 'value': e['value'],
                    'score_a': e['score_a'], 'score_b': e['score_b']})

    # ---------- margin timeline (one point per score change) ----------
    tl = [{'t': 0, 'p': 1, 'clock': '12:00', 'a': 0, 'b': 0, 'm': 0}]
    seen = (0, 0)
    for e, disp in zip(ev, pbp):
        if (e['score_a'], e['score_b']) != seen:
            seen = (e['score_a'], e['score_b'])
            tl.append({'t': e['elapsed'], 'p': e['period'], 'clock': e['clock'],
                       'a': e['score_a'], 'b': e['score_b'],
                       'm': e['score_b'] - e['score_a'],
                       'by': e['team'], 'who': e['player'], 'what': disp['act']})
    tl.append(dict(tl[-1], t=full_time, clock='00:00', p=nper))

    # ---------- shot profile ----------
    prof = {}
    for t in codes:
        agg = collections.defaultdict(lambda: [0, 0])
        for e in ev:
            if e['team'] == t and e['type'] == 'shot':
                k = (e['subtype'].replace(' shot', '').replace('jump_', 'jump'), e['value'])
                agg[k][1] += 1
                if e['made']:
                    agg[k][0] += 1
        prof[t] = [{'type': k[0], 'val': k[1], 'made': v[0], 'att': v[1]}
                   for k, v in sorted(agg.items(), key=lambda x: (x[0][1], -x[1][1]))]

    # ---------- longest unanswered runs ----------
    def runs(team, floor=7):
        out, cur, start, last = [], 0, None, None
        for e in ev:
            if e['made'] is not True:
                continue
            if e['team'] == team:
                if cur == 0:
                    start = e
                cur += e['value']; last = e
            else:
                if cur >= floor:
                    out.append({'pts': cur, 'from': 'P%d %s' % (start['period'], start['clock']),
                                'to': 'P%d %s' % (last['period'], last['clock'])})
                cur = 0
        if cur >= floor:
            out.append({'pts': cur, 'from': 'P%d %s' % (start['period'], start['clock']),
                        'to': 'P%d %s' % (last['period'], last['clock'])})
        return sorted(out, key=lambda r: -r['pts'])

    # ---------- team four factors ----------
    TM = {t: _totals(g['teams'][t]['totals']) for t in codes}
    for t in codes:
        m = TM[t]
        m['poss_raw'] = m['fga'] - m['orb'] + m['to'] + 0.44 * m['fta']
        assert m['p2m'] * 2 + m['p3m'] * 3 + m['p4m'] * 4 + m['ftm'] == m['pts'], \
            'points do not reconcile for %s' % t
    POSS = (TM[A]['poss_raw'] + TM[B]['poss_raw']) / 2

    adv_team = {}
    for t in codes:
        m, o = TM[t], TM[B if t == A else A]
        ptsfg = m['p2m'] * 2 + m['p3m'] * 3 + m['p4m'] * 4
        adv_team[t] = {
            'poss': round(POSS, 1),
            'ortg': round(100 * m['pts'] / POSS, 1),
            'drtg': round(100 * o['pts'] / POSS, 1),
            'net': round(100 * (m['pts'] - o['pts']) / POSS, 1),
            'efg': round(100 * ptsfg / (2 * m['fga']), 1),
            'ts': round(100 * m['pts'] / (2 * (m['fga'] + 0.44 * m['fta'])), 1),
            'tov': round(100 * m['to'] / m['poss_raw'], 1),
            'orb': round(100 * m['orb'] / (m['orb'] + o['drb']), 1),
            'drb': round(100 * m['drb'] / (m['drb'] + o['orb']), 1),
            'ftr': round(100 * m['ftm'] / m['fga'], 1),
            'ast_fgm': round(100 * m['ast'] / m['fgm'], 1),
            'ppp': round(m['pts'] / POSS, 3),
        }

    # ---------- player rates ----------
    TMIN = 5 * (48 + 5 * max(0, nper - 4))
    adv_players = {}
    for t in codes:
        m, o = TM[t], TM[B if t == A else A]
        rows = []
        for p in g['teams'][t]['players']:
            mn = mins2f(p['mins'])
            fgm, fga = ma(p['fg']); p3m, p3a = ma(p['p3'])
            p4m, p4a = ma(p['p4']); ftm, fta = ma(p['ft'])
            p2m = fgm - p3m - p4m
            ptsfg = p2m * 2 + p3m * 3 + p4m * 4
            tsa = fga + 0.44 * fta
            f = (TMIN / 5) / mn if mn else 0
            pct = lambda num, den: None if den <= 0 else round(100 * num / den, 1)
            rows.append(dict(
                no=p['no'], name=p['player'], group=p['group'], mins=p['mins'],
                min=round(mn, 2), pts=p['pts'], reb=p['reb'], ast=p['ast'],
                to=p['to'], pm=p['pm'], fga=fga, fta=fta, tsa=round(tsa, 1),
                ts=pct(p['pts'], 2 * tsa) if tsa > 0 else None,
                efg=pct(ptsfg, 2 * fga) if fga > 0 else None,
                usg=pct((fga + 0.44 * fta + p['to']) * f,
                        m['fga'] + 0.44 * m['fta'] + m['to']) if mn else None,
                astp=pct(p['ast'] * f, m['fgm'] - fgm * f)
                     if mn and (m['fgm'] - fgm * f) > 0 else None,
                orbp=pct(p['off'] * f, m['orb'] + o['drb']) if mn else None,
                drbp=pct(p['def'] * f, m['drb'] + o['orb']) if mn else None,
                trbp=pct(p['reb'] * f, m['trb'] + o['trb']) if mn else None,
                stlp=pct(p['stl'] * f, POSS) if mn else None,
                blkp=pct(p['blk'] * f, o['p2a']) if mn and o['p2a'] else None,
                tovp=pct(p['to'], fga + 0.44 * fta + p['to'])
                     if (fga + 0.44 * fta + p['to']) > 0 else None,
                gmsc=round(p['pts'] + 0.4 * fgm - 0.7 * fga - 0.4 * (fta - ftm)
                           + 0.7 * p['off'] + 0.3 * p['def'] + p['stl'] + 0.7 * p['ast']
                           + 0.7 * p['blk'] - 0.4 * p['pf'] - p['to'], 1),
                # on-court net rating from the OFFICIAL plus-minus, not a reconstruction
                onnet=None if mn < 1 else round(100 * p['pm'] / (POSS * mn / 48.0), 1),
                p36=None if mn < 1 else round(p['pts'] * 36 / mn, 1),
                r36=None if mn < 1 else round(p['reb'] * 36 / mn, 1),
                a36=None if mn < 1 else round(p['ast'] * 36 / mn, 1),
            ))
        adv_players[t] = rows
        assert sum(r['pts'] for r in rows) == m['pts'], 'player points do not sum for %s' % t

    # ---------- assists, verified against the box ----------
    short_of = {}
    for t in codes:
        pbp_names = {e['player'] for e in ev if e['team'] == t and e['player']}
        pbp_names |= {e['sub_in'] for e in ev if e['team'] == t and e['sub_in']}
        pbp_names |= {e['sub_out'] for e in ev if e['team'] == t and e['sub_out']}
        pbp_names |= {e['assist'] for e in ev if e['team'] == t and e['assist']}
        for p in g['teams'][t]['players']:
            box, init = p['player'], p['player'][0].lower()
            tail = box.split('. ', 1)[1] if '. ' in box else box
            cand = [n for n in pbp_names
                    if n.lower().replace('.', '').endswith(tail.lower().replace('.', ''))
                    and n[0].lower() == init]
            if len(cand) == 1:
                short_of[cand[0]] = box

    pairs = collections.Counter()
    for e in ev:
        if e['made'] and e['assist']:
            pairs[(e['team'], e['assist'], e['player'])] += 1
    assist_pairs = [{'team': k[0], 'from': short_of.get(k[1], k[1]),
                     'to': short_of.get(k[2], k[2]), 'n': v}
                    for k, v in sorted(pairs.items(), key=lambda x: -x[1])]
    for t in codes:
        got = sum(a['n'] for a in assist_pairs if a['team'] == t)
        assert got == TM[t]['ast'], 'assists %d != box %d for %s' % (got, TM[t]['ast'], t)

    gp = TM[A]['pts'] + TM[B]['pts']
    gfa = TM[A]['fga'] + TM[B]['fga']
    gft = TM[A]['fta'] + TM[B]['fta']

    teams_out = {}
    for t in codes:
        teams_out[t] = {'name': g['name_a'] if t == A else g['name_b'],
                        'coach': g['teams'][t]['coach'],
                        'players': g['teams'][t]['players'],
                        'totals': g['teams'][t]['totals']}

    return {
        'codes': codes,
        'meta': {'venue': g['venue'], 'datetime': g['datetime'],
                 'game_id': game_id, 'source': source_url},
        'quarters': g['quarters'], 'periods': nper, 'final': g['final'],
        'teams': teams_out,
        'comparison': [{'a': c['a'], 'label': c['label'], 'b': c['b']}
                       for c in g['comparison']],
        'pbp': pbp, 'timeline': tl, 'shotprofile': prof,
        'runs': {t: runs(t) for t in codes},
        'halves': {t: [sum(g['quarters'][t][:2]), sum(g['quarters'][t][2:])] for t in codes},
        'leads': {'b_max': max(p['m'] for p in tl), 'a_max': -min(p['m'] for p in tl)},
        'advTeam': adv_team, 'advPlayers': adv_players,
        'assistPairs': assist_pairs,
        'gameTS': round(100 * gp / (2 * (gfa + 0.44 * gft)), 1),
        'checks': c,
    }
