"""A box plus/minus model fit to PBA data.

BPM 2.0 cannot be reproduced here: its published method depends on shooting-location
data this feed does not carry, and on position/role regression coefficients that are
not published. Rather than transplant NBA coefficients, this fits the same *shape* of
model -- box-score rates per 100 possessions -> plus-minus per 100 possessions -- to
the conference's own official plus-minus, then applies the standard team adjustment.

Honest evaluation: scored with GroupKFold grouped by TEAM, so a model that has merely
learned "this player was on a good team" cannot score well.
"""
import json, sys, numpy as np
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
import metrics
from paths import DERIVED

FEATS = ['pts','fga','fta','bonus','ast','to','orb','drb','stl','blk','pf']
MIN_MINUTES = 60          # season minutes required to enter the fit
REPLACEMENT = -2.0        # BBRef's replacement level, in points per 100


def feature_rows(M):
    """Per-100-possession box rates for each qualifying player-season."""
    T = M['teams']
    X, y, w, g, keep = [], [], [], [], []
    for r in M['players']:
        t = T[r['team']]
        # possessions the player was on the floor for
        poss = t['poss'] * r['min'] / (t['mp']/5)
        if r['min'] < MIN_MINUTES or poss <= 0:
            continue
        s = 100.0 / poss
        X.append([r['pts']*s, r['fga']*s, r['fta']*s,
                  (r['p3m'] + 2*r['p4m'])*s, r['ast']*s, r['to']*s,
                  r['orb']*s, r['drb']*s, r['stl']*s, r['blk']*s, r['pf']*s])
        y.append(r['pm100'])
        w.append(r['min'])
        g.append(r['team'])
        keep.append(r)
    return np.array(X), np.array(y), np.array(w), np.array(g), keep


def wr2(y, p, w):
    ybar = np.average(y, weights=w)
    ss_res = np.sum(w*(y-p)**2)
    ss_tot = np.sum(w*(y-ybar)**2)
    return 1 - ss_res/ss_tot


def fit(M, label, alpha=10.0):
    X, y, w, g, keep = feature_rows(M)
    model = make_pipeline(StandardScaler(), Ridge(alpha=alpha))
    model.fit(X, y, ridge__sample_weight=w)
    insample = model.predict(X)

    cv = GroupKFold(n_splits=min(13, len(set(g))))
    oof = np.zeros_like(y)
    for tr, te in cv.split(X, y, groups=g):
        m2 = make_pipeline(StandardScaler(), Ridge(alpha=alpha))
        m2.fit(X[tr], y[tr], ridge__sample_weight=w[tr])
        oof[te] = m2.predict(X[te])
    r2_in, r2_cv = wr2(y, insample, w), wr2(y, oof, w)

    print('  %-20s n=%3d  in-sample wR2=%.3f   team-grouped CV wR2=%.3f'
          % (label, len(y), r2_in, r2_cv))

    # raw BPM for every player with minutes (including those below the fit threshold)
    T = M['teams']
    raw = {}
    for r in M['players']:
        t = T[r['team']]
        poss = t['poss']*r['min']/(t['mp']/5)
        if poss <= 0:
            raw[(r['team'], r['name'])] = 0.0; continue
        s = 100.0/poss
        v = np.array([[r['pts']*s, r['fga']*s, r['fta']*s,
                       (r['p3m'] + 2*r['p4m'])*s, r['ast']*s, r['to']*s,
                       r['orb']*s, r['drb']*s, r['stl']*s, r['blk']*s, r['pf']*s]])
        raw[(r['team'], r['name'])] = float(model.predict(v)[0])

    # team adjustment: minute-weighted team BPM must equal the team's net rating
    adj = {}
    for c, t in T.items():
        rows = [r for r in M['players'] if r['team'] == c and r['min'] > 0]
        mw = sum(raw[(c, r['name'])]*r['min'] for r in rows) / sum(r['min'] for r in rows)
        adj[c] = t['net'] - mw

    for r in M['players']:
        c = r['team']
        if r['min'] <= 0:
            r['bpm'] = r['vorp'] = r['vorp82'] = None
            continue
        t = T[c]
        r['bpm'] = raw[(c, r['name'])] + adj[c]
        share = r['min'] / (t['mp']/5)                 # share of one lineup slot
        r['vorp'] = (r['bpm'] - REPLACEMENT) * share * (t['g']/82.0)
        r['vorp82'] = (r['bpm'] - REPLACEMENT) * share

    # verify the adjustment held
    worst = 0.0
    for c, t in T.items():
        rows = [r for r in M['players'] if r['team'] == c and r['min'] > 0]
        mw = sum(r['bpm']*r['min'] for r in rows)/sum(r['min'] for r in rows)
        worst = max(worst, abs(mw - t['net']))
    print('      team adjustment check: max |team BPM - team net rating| = %.6f' % worst)

    coefs = dict(zip(FEATS, model.named_steps['ridge'].coef_ /
                     model.named_steps['standardscaler'].scale_))
    return {'r2_in': r2_in, 'r2_cv': r2_cv, 'n': int(len(y)),
            'coef_per100': {k: round(v, 4) for k, v in coefs.items()},
            'min_minutes': MIN_MINUTES, 'replacement': REPLACEMENT}


if __name__ == '__main__':
    for which in (sys.argv[1:] or ['gov','comm']):
        s = json.load(open(DERIVED / ('season_%s.json' % which), encoding='utf-8'))
        M = metrics.build(s)
        print('== %s ==' % s['label'])
        info = fit(M, s['label'])
        P = sorted([r for r in M['players'] if r['bpm'] is not None],
                   key=lambda r: -r['vorp82'])[:8]
        print('      %-22s %-4s %5s %6s %6s %6s %7s' % ('TOP BY VORP/82','TM','MIN','PER','WS','BPM','VORP/82'))
        for r in P:
            print('      %-22s %-4s %5.0f %6.1f %6.2f %+6.1f %7.2f'
                  % (r['name'], r['team'], r['min'], r['per'], r['ws'], r['bpm'], r['vorp82']))
        print('      coefficients (pts per 100 poss, per unit of each per-100 stat):')
        print('      ', info['coef_per100'])
