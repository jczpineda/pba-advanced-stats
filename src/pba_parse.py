"""Parse one PBA game page from the actech2 stats frame into a dict.

Generalised from the single-game parser: handles overtime, any team pair, and
games whose play-by-play prints the running score on either side (or neither).
"""
import re, html

COLS = ['no','player','mins','pts','fg','fg_pct','p2','p2_pct','p3','p3_pct','p4','p4_pct',
        'ft','ft_pct','off','def','reb','ast','to','stl','blk','pf','fls_on','pm']
QLEN_REG, QLEN_OT = 720, 300          # PBA: 12-minute quarters, 5-minute overtimes


def clean(s):
    s = re.sub(r'<[^>]+>', ' ', s)
    return re.sub(r'\s+', ' ', html.unescape(s)).strip()


def period_start(p):
    """Seconds of elapsed game time at the start of period p (1-indexed)."""
    return (p - 1) * QLEN_REG if p <= 4 else 4 * QLEN_REG + (p - 5) * QLEN_OT


def period_len(p):
    return QLEN_REG if p <= 4 else QLEN_OT


def parse_box(tab):
    rows, group, totals = [], 'starters', None
    for tr in re.findall(r'<tr.*?</tr>', tab, re.S):
        cells = [c for c in (clean(c) for c in
                 re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.S)) if c]
        if not cells or cells[0] == 'NO.':
            continue
        if cells[0].lower() in ('starters', 'bench'):
            group = cells[0].lower(); continue
        if cells[0] == 'TEAM TOTALS':
            totals = dict(zip(COLS[2:], cells[1:])); continue
        if len(cells) != len(COLS):
            continue
        r = dict(zip(COLS, cells)); r['group'] = group
        for k in ('pts','off','def','reb','ast','to','stl','blk','pf','fls_on','pm'):
            r[k] = int(r[k].replace('+', ''))
        for k in ('fg_pct','p2_pct','p3_pct','p4_pct','ft_pct'):
            r[k] = float(r[k])
        rows.append(r)
    return rows, totals


def parse_game(h, game_id):
    """Return a game dict, or None if the page carries no completed box score."""
    tabs = re.findall(r'<table.*?</table>', h, re.S)
    if len(tabs) < 3:
        return None

    # ---- quarter strip: first table is "ABC q1 q2 q3 q4 [ot...]" twice ----
    qcells = clean(tabs[0]).split()
    codes = [c for c in qcells if re.fullmatch(r'[A-Z]{3}', c)]
    if len(codes) != 2:
        return None
    a_code, b_code = codes
    ia, ib = qcells.index(a_code), qcells.index(b_code)
    qa = [int(x) for x in qcells[ia+1:ib]]
    qb = [int(x) for x in qcells[ib+1:]]
    if not qa or len(qa) != len(qb):
        return None

    # ---- metadata ----
    seg = clean(re.sub(r'<script.*?</script>', '', h[:h.find(tabs[1])], flags=re.S))
    mv = re.search(r'Venue (.*?) Game Details', seg)
    md = re.search(r'Game Details (\d\d/\d\d/\d\d \d\d:\d\d [AP]M)', seg)
    # full team names live in the box-score title block, keyed by 3-letter code
    nm_pairs = re.findall(r'team_code"[^>]*>\s*([A-Z]{3})\s*</div>\s*'
                          r'<div class="team_name">\s*(.*?)\s*</div>', h, re.S)
    name_of = {c: clean(n) for c, n in nm_pairs}
    coaches = re.findall(r'Coach:</h4>\s*<span>([^<]+)<', h)

    teams = {}
    for key, tab in ((a_code, tabs[1]), (b_code, tabs[2])):
        players, totals = parse_box(tab)
        if not players or not totals:
            return None
        teams[key] = {'players': players, 'totals': totals}
    # coach list repeats; take the first occurrence per team in page order
    seen = []
    for c in coaches:
        c = clean(c)
        if c not in seen:
            seen.append(c)
    for i, k in enumerate((a_code, b_code)):
        teams[k]['coach'] = seen[i] if i < len(seen) else ''

    # ---- team comparison ----
    comparison = []
    if len(tabs) >= 8:
        for tr in re.findall(r'<tr.*?</tr>', tabs[7], re.S):
            cells = [c for c in (clean(c) for c in
                     re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.S)) if c]
            if len(cells) == 3:
                try:
                    comparison.append({'a': float(cells[0]), 'label': cells[1],
                                       'b': float(cells[2])})
                except ValueError:
                    pass

    # ---- play by play ----
    blocks = re.findall(
        r'<div id="(\d\d:\d\d)" class="pbpa pbpt(\d) pbpty(\w+) per_p(\d+) ([^"]*)">(.*?)'
        r'(?=<div id="\d\d:\d\d" class="pbpa|</div>\s*</div>\s*</div>)', h, re.S)
    # Two feed dialects exist, and the CSS class names are identical in both --
    # only the ACTION TEXT differs, so sniff that:
    #   NEW: "made 2pt jump_shot" / "missed 3pt jump_shot", "(AST: X)", "SUB: X in for Y"
    #   OLD: misses tagged "MISS", made field goals UNMARKED, free throws tagged
    #        "MADE"/"MISS", "(X Assist)", "Sub: X for Y"
    _texts = [clean(b[5]) for b in blocks]
    _new = sum(1 for t in _texts if ' made ' in ' '+t.lower() or ' missed ' in ' '+t.lower())
    _old = sum(1 for t in _texts if re.search(r'\bMISS\b|\bMADE\b', t))
    old = _old > _new

    events = []
    for clock, tnum, typ, per, sub, body in blocks:
        txt = re.sub(r'P\d+ \d\d:\d\d', '', clean(body)).strip()
        sc = re.search(r'(\d+) - (\d+)', txt)
        pa = pb = None
        if sc:
            pa, pb = int(sc.group(1)), int(sc.group(2))
            txt = (txt[:sc.start()] + ' ' + txt[sc.end():]).strip()
        pm_ = re.search(r'<strong>(.*?)</strong>', body, re.S)
        player = clean(pm_.group(1)) if pm_ else ''
        desc = txt
        while player and desc.startswith(player):
            desc = desc[len(player):].strip()
        mv2 = re.search(r'(\d)\s?pt', txt, re.I)
        val = int(mv2.group(1)) if mv2 else (1 if typ == 'free_throw' else None)
        if old:
            if re.search(r'\bMISS\b', txt):      made = False
            elif re.search(r'\bMADE\b', txt):    made = True
            elif typ == 'shot':                   made = True   # unmarked == made
            else:                                 made = None
            am = re.search(r'\(([^)]+?) Assist\)', txt)
            sm = re.match(r'(?:.*?)\bSub: (.+?) for (.+?)$', txt)
        else:
            low = ' ' + txt.lower() + ' '
            made = True if ' made ' in low else (False if ' missed ' in low else None)
            am = re.search(r'\(AST: (.+?)\)', txt)
            sm = re.search(r'SUB: (.+?) in for (.+?)$', txt)
        assist = clean(am.group(1)) if am else ''
        sub_in, sub_out = (clean(sm.group(1)), clean(sm.group(2))) if sm else ('', '')
        p = int(per)
        mi, se = int(clock[:2]), int(clock[3:])
        events.append({
            'period': p, 'clock': clock,
            'elapsed': period_start(p) + (period_len(p) - (mi * 60 + se)),
            'team': a_code if tnum == '1' else b_code,
            'type': typ, 'subtype': (sub.replace(typ, '').strip() or typ),
            'player': player, 'act': re.sub(r'\s+', ' ', desc).strip(),
            'made': made, 'value': val, 'sa': pa, 'sb': pb,
            'assist': assist, 'sub_in': sub_in, 'sub_out': sub_out,
        })
    events.reverse()

    # ---- running score: rebuild from made events, check against printed anchors ----
    anchors = [(i, e['sa'], e['sb']) for i, e in enumerate(events) if e['sa'] is not None]
    sa = sb = 0
    for e in events:
        if e['made'] and e['value']:
            if e['team'] == a_code: sa += e['value']
            else: sb += e['value']
        e['score_a'], e['score_b'] = sa, sb
        e.pop('sa', None); e.pop('sb', None)
    anchor_bad = sum(1 for i, x, y in anchors
                     if (events[i]['score_a'], events[i]['score_b']) != (x, y))

    fa, fb = sum(qa), sum(qb)
    return {
        'game_id': game_id,
        'venue': mv.group(1).strip() if mv else '',
        'datetime': md.group(1) if md else '',
        'a': a_code, 'b': b_code,
        'name_a': name_of.get(a_code, a_code),
        'name_b': name_of.get(b_code, b_code),
        'quarters': {a_code: qa, b_code: qb},
        'periods': len(qa),
        'final': {a_code: fa, b_code: fb},
        'teams': teams,
        'comparison': comparison,
        'pbp': events, 'dialect': 'old' if old else 'new',
        'checks': {
            'anchors': len(anchors), 'anchor_bad': anchor_bad,
            'pbp_final_ok': (sa, sb) == (fa, fb),
            'box_sum_ok': all(sum(p['pts'] for p in teams[k]['players']) == f
                              for k, f in ((a_code, fa), (b_code, fb))),
        },
    }
