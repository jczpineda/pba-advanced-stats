"""Assemble league.json from both conferences and inject it into the HTML template."""
import collections
import json

import build_league
import game_detail
import metrics
from paths import CONFERENCES, DERIVED, DIST, TEMPLATE, raw_path

CASE_STUDY_GAME = 601          # the game the dashboard's second tab walks through

PKEEP = ['qual', 'team', 'name', 'g', 'gs', 'min', 'mpg', 'pts', 'reb', 'ast', 'stl',
         'blk', 'to', 'pf', 'pm', 'fgm', 'fga', 'p3m', 'p3a', 'p4m', 'p4a', 'ftm', 'fta',
         'orb', 'drb', 'ppg', 'rpg', 'apg', 'spg', 'bpg', 'topg', 'fgp', 'p3p', 'ftp',
         'ts', 'efg', 'usg', 'astp', 'orbp', 'drbp', 'trbp', 'stlp', 'blkp', 'tovp',
         'per', 'ws', 'ows', 'dws', 'ws48', 'ortg_i', 'drtg_i', 'pm100']
TKEEP = ['code', 'g', 'w', 'l', 'poss', 'pace', 'ortg', 'drtg', 'net', 'efg', 'ts',
         'tov', 'orb', 'drb', 'ftr', 'ppg', 'papg']

LIMITS = {
  'bpm': ("BPM 2.0 is not reproducible from this feed: its published method needs "
          "shooting-location data the feed does not carry, plus position and offensive-role "
          "regression coefficients Basketball-Reference does not publish. Refitting a "
          "BPM-shaped model on the league's own plus-minus was tried and rejected: across "
          "339 qualifying player-seasons it reached a team-grouped cross-validated R² of "
          "only 0.17, and the fitted coefficients claimed that committing fouls helps "
          "(+0.85 points per 100) and that three-point shooting hurts (−0.27). That model "
          "is fitting noise, not basketball, so no BPM or VORP is published here."),
  'lineups': ("Lineup on/off and five-man data are not published. The play-by-play logs many "
              "substitutions but omits others, so a reconstructed lineup disagrees with the "
              "official minutes. Plus-minus shown everywhere is the official box figure."),
  'sample': ("Conferences run 10-27 games per team. Rate stats over that span are noisy; "
             "leaderboards apply a minutes qualifier and the tables mark players below it."),
}
METHOD = {
  'per': ("Hollinger's PER, adapted for the PBA 4-point line (the formula's bonus-point term "
          "becomes 3PM + 2×4PM). Pace-adjusted per team and normalised so each conference's "
          "minute-weighted average is exactly 15.00."),
  'ws': ("Oliver's Offensive and Defensive Win Shares as implemented by Basketball-Reference. "
         "Validated against actual results: summed Win Shares come to 73.7 against 74 real wins "
         "in the Governors' Cup and 102.4 against 103 in the Commissioner's Cup."),
  'poss': ("Possessions use Basketball-Reference's estimate, averaging both teams' figures so "
           "the two sides of a game share one pace."),
}
GAME_NOTES = {
  'noLineups': ("Lineup on/off is not published here: the feed logs 59 substitutions but "
                "omits others, so a reconstructed lineup disagrees with the official minutes "
                "for 8 of 25 players. The plus-minus shown is the official box figure."),
  'noPER': ("PER, Win Shares, BPM and VORP are omitted on purpose. All four are defined "
            "against league-wide baselines across a season; from a single game there is "
            "nothing to calibrate them with."),
}


def conference_block(which):
    season = build_league.build(which)
    M = metrics.build(season)

    names = {}
    for g in season['games']:
        names[g['a']] = g['name_a']
        names[g['b']] = g['name_b']

    players = [{k: (round(r[k], 3) if isinstance(r.get(k), float) else r.get(k))
                for k in PKEEP} for r in M['players']]
    teams = []
    for c, t in M['teams'].items():
        d = {k: (round(t[k], 3) if isinstance(t[k], float) else t[k]) for k in TKEEP}
        d['name'] = names.get(c, c)
        teams.append(d)
    teams.sort(key=lambda d: (-d['w'], d['l']))

    # Leaderboard qualifier: at least half the team's games AND 15+ minutes per game.
    # A minutes-only floor let six-minute cameos top the rate leaderboards.
    tg = {t['code']: t['g'] for t in teams}
    for p in players:
        p['qual'] = 1 if (p['g'] >= 0.5 * tg[p['team']] and p['mpg'] >= 15) else 0

    dup = [n for n, c in collections.Counter(p['name'] for p in players).items() if c > 1]
    print('%-5s %-20s teams=%2d players=%3d games=%3d qualified=%3d multi-team=%d'
          % (which, season['label'], len(teams), len(players), len(season['games']),
             sum(p['qual'] for p in players), len(dup)))

    return {
        'key': which, 'label': season['label'],
        'games': season['games'], 'teams': teams, 'players': players,
        'league': {k: (round(v, 4) if isinstance(v, float) else v)
                   for k, v in M['league'].items()},
        'qual_rule': 'at least half the team’s games and 15+ minutes per game',
        'n_qual': sum(p['qual'] for p in players),
        'ot_games': season['ot_games'],
    }


def case_study(game_id):
    """One game, keyed the way the dashboard's game tab reads it.

    game_detail is generic across the archive; this view is a written walk-through of
    one game, so its keys are renamed from a/b to that game's two team codes.
    """
    html = raw_path(game_id).read_text(encoding='utf-8', errors='replace')
    d = game_detail.build(html, game_id, 'https://pba.ph/recap?match=%d' % game_id)
    A, B = d['codes']
    for e in d['pbp']:
        e['score_mag'], e['score_tnt'] = e.pop('score_a'), e.pop('score_b')
    for p in d['timeline']:
        p['mag'], p['tnt'] = p.pop('a'), p.pop('b')
    for c in d['comparison']:
        c['mag'], c['tnt'] = c.pop('a'), c.pop('b')
    d['leads'] = {'mag_max': d['leads']['a_max'], 'tnt_max': d['leads']['b_max']}
    d['meta']['competition'] = "PBA 50th Season Governors' Cup"
    d['notes'] = GAME_NOTES
    print('case study  game %d  %s %d-%d %s  (%s)'
          % (game_id, A, d['final'][A], d['final'][B], B, d['meta']['datetime']))
    return d


def main():
    out = {'conferences': {}, 'order': list(CONFERENCES)}
    for which in CONFERENCES:
        out['conferences'][which] = conference_block(which)
    out['game601'] = case_study(CASE_STUDY_GAME)
    out['limits'] = LIMITS
    out['method'] = METHOD

    league_path = DERIVED / 'league.json'
    payload = json.dumps(out, separators=(',', ':'), ensure_ascii=False)
    league_path.write_text(payload, encoding='utf-8')

    tpl = TEMPLATE.read_text(encoding='utf-8')
    if '__LEAGUE__' not in tpl:
        raise SystemExit('template is missing the __LEAGUE__ placeholder')
    if '</script' in payload.lower():
        raise SystemExit('data would terminate the inline script')
    html = tpl.replace('__LEAGUE__', payload)
    dest = DIST / 'dashboard.html'
    dest.write_text(html, encoding='utf-8')
    print('league.json  %.1f KB' % (league_path.stat().st_size / 1024))
    print('dashboard    %.1f KB  ->  %s' % (dest.stat().st_size / 1024, dest))


if __name__ == '__main__':
    main()
