"""Advanced metrics for a PBA conference.

PER  : Hollinger, adapted for the PBA 4-point line (the NBA formula's "3P" term
       is the bonus point a three earns over a two; here it becomes 3PM + 2*4PM).
       Normalised so the minute-weighted league average is exactly 15.
WS   : Oliver's Offensive/Defensive Win Shares as implemented by Basketball-Reference.
       Validated against actual team wins.
"""
import json

SUM_KEYS = ('pts','off','def','reb','ast','to','stl','blk','pf','fgm','fga',
            'p3m','p3a','p4m','p4a','ftm','fta','min','pm')


def agg(rows):
    t = {k: 0 for k in SUM_KEYS}
    for r in rows:
        for k in SUM_KEYS:
            t[k] += r.get(k, 0)
    return t


def team_possessions(tm, op):
    """Basketball-Reference team possession estimate (averages both sides)."""
    a = tm['fga'] + 0.4*tm['fta'] - 1.07*(tm['off']/max(tm['off']+op['def'], 1))*(tm['fga']-tm['fgm']) + tm['to']
    b = op['fga'] + 0.4*op['fta'] - 1.07*(op['off']/max(op['off']+tm['def'], 1))*(op['fga']-op['fgm']) + op['to']
    return 0.5*(a+b)


def build(season):
    teams, opps, rec = season['teams'], season['opps'], season['rec']
    codes = sorted(teams)

    # ---------- team level ----------
    T = {}
    for c in codes:
        tm, op, r = teams[c], opps[c], rec[c]
        poss = team_possessions(tm, op)
        oposs = team_possessions(op, tm)
        mp = tm['min']                                  # summed player minutes
        pace = 48 * poss / (mp/5)
        ptsfg = 2*(tm['fgm']-tm['p3m']-tm['p4m']) + 3*tm['p3m'] + 4*tm['p4m']
        T[c] = dict(
            code=c, g=r['g'], w=r['w'], l=r['l'], mp=mp, poss=poss, oposs=oposs, pace=pace,
            pf_=r['pf'], pa_=r['pa'],
            ortg=100*tm['pts']/poss, drtg=100*op['pts']/oposs,
            efg=100*ptsfg/(2*tm['fga']),
            ts=100*tm['pts']/(2*(tm['fga']+0.44*tm['fta'])),
            tov=100*tm['to']/poss,
            orb=100*tm['off']/(tm['off']+op['def']),
            drb=100*tm['def']/(tm['def']+op['off']),
            ftr=100*tm['ftm']/tm['fga'],
            ppg=tm['pts']/r['g'], papg=op['pts']/r['g'],
            **{('tm_'+k): tm[k] for k in SUM_KEYS},
            **{('op_'+k): op[k] for k in SUM_KEYS},
        )
        T[c]['net'] = T[c]['ortg'] - T[c]['drtg']

    lg = agg([teams[c] for c in codes])
    lgop = agg([opps[c] for c in codes])
    lg_poss = sum(T[c]['poss'] for c in codes)
    lg_mp   = sum(T[c]['mp'] for c in codes)
    lg_pace = 48 * lg_poss / (lg_mp/5)
    lg_ppp  = lg['pts']/lg_poss
    lg_ppg  = lg['pts'] / sum(T[c]['g'] for c in codes)      # points per team-game

    L = dict(pace=lg_pace, ppp=lg_ppp, ppg=lg_ppg, poss=lg_poss, mp=lg_mp,
             **{k: lg[k] for k in SUM_KEYS})

    # ---------- PER constants ----------
    factor = (2/3) - (0.5*(lg['ast']/lg['fgm'])) / (2*(lg['fgm']/lg['ftm']))
    VOP    = lg['pts'] / (lg['fga'] - lg['off'] + lg['to'] + 0.44*lg['fta'])
    DRBP   = (lg['reb'] - lg['off']) / lg['reb']
    L.update(factor=factor, vop=VOP, drbp=DRBP)

    # ---------- players ----------
    out = []
    for p in season['players']:
        c = p['team']
        if p['min'] <= 0:
            continue
        tm, op, t = teams[c], opps[c], T[c]
        MP, FG, FGA = p['min'], p['fgm'], p['fga']
        FT, FTA = p['ftm'], p['fta']
        AST, TOV, ORB, DRB, TRB = p['ast'], p['to'], p['off'], p['def'], p['reb']
        STL, BLK, PF, PTS = p['stl'], p['blk'], p['pf'], p['pts']
        bonus = p['p3m'] + 2*p['p4m']            # points above 2 per made FG
        tmAST_FG = tm['ast']/tm['fgm']

        uPER = (1/MP) * (
            bonus
            + (2/3)*AST
            + (2 - factor*tmAST_FG)*FG
            + FT*0.5*(1 + (1-tmAST_FG) + (2/3)*tmAST_FG)
            - VOP*TOV
            - VOP*DRBP*(FGA-FG)
            - VOP*0.44*(0.44 + 0.56*DRBP)*(FTA-FT)
            + VOP*(1-DRBP)*(TRB-ORB)
            + VOP*DRBP*ORB
            + VOP*STL
            + VOP*DRBP*BLK
            - PF*((lg['ftm']/lg['pf']) - 0.44*(lg['fta']/lg['pf'])*VOP)
        )
        aPER = (lg_pace/t['pace'])*uPER

        # ----- Win Shares: offensive -----
        tmMP, tmFG, tmFGA = tm['min'], tm['fgm'], tm['fga']
        tmFT, tmFTA, tmPTS = tm['ftm'], tm['fta'], tm['pts']
        tmAST, tmORB, tmTOV = tm['ast'], tm['off'], tm['to']
        tm3 = tm['p3m'] + 2*tm['p4m']
        if FGA > 0 and tmFGA - FGA > 0 and tmFG - FG > 0:
            qAST = ((MP/(tmMP/5)) * (1.14*((tmAST-AST)/tmFG))) + \
                   ((((tmAST/tmMP)*MP*5 - AST) / ((tmFG/tmMP)*MP*5 - FG)) * (1 - MP/(tmMP/5))) \
                   if ((tmFG/tmMP)*MP*5 - FG) != 0 else 0.0
        else:
            qAST = 0.0
        FG_Part  = FG * (1 - 0.5*((PTS-FT)/(2*FGA))*qAST) if FGA > 0 else 0.0
        AST_Part = 0.5*(((tmPTS-tmFT) - (PTS-FT)) / (2*(tmFGA-FGA)))*AST if tmFGA-FGA > 0 else 0.0
        FT_Part  = (1 - (1 - (FT/FTA))**2)*0.4*FTA if FTA > 0 else 0.0
        tmScPoss = tmFG + (1 - (1 - (tmFT/tmFTA))**2)*tmFTA*0.4
        tmORBp   = tmORB/(tmORB + op['def'])
        tmPlay   = tmScPoss/(tmFGA + tmFTA*0.4 + tmTOV)
        tmORBW   = ((1-tmORBp)*tmPlay) / ((1-tmORBp)*tmPlay + tmORBp*(1-tmPlay))
        ORB_Part = ORB*tmORBW*tmPlay
        ScPoss   = (FG_Part + AST_Part + FT_Part)*(1 - (tmORB/tmScPoss)*tmORBW*tmPlay) + ORB_Part
        FGxPoss  = (FGA-FG)*(1 - 1.07*tmORBp)
        FTxPoss  = ((1-(FT/FTA))**2)*0.4*FTA if FTA > 0 else 0.0
        TotPoss  = ScPoss + FGxPoss + FTxPoss + TOV

        ptsfg_p = 2*(FG - p['p3m'] - p['p4m']) + 3*p['p3m'] + 4*p['p4m']
        PProd_FG = ptsfg_p * (1 - 0.5*((PTS-FT)/(2*FGA))*qAST) if FGA > 0 else 0.0
        PProd_AST = 2*((tmFG-FG + 0.5*(tm3 - bonus))/(tmFG-FG)) * 0.5 * \
                    (((tmPTS-tmFT)-(PTS-FT))/(2*(tmFGA-FGA))) * AST \
                    if (tmFG-FG) > 0 and (tmFGA-FGA) > 0 else 0.0
        PProd_ORB = ORB*tmORBW*tmPlay*(tmPTS/tmScPoss)
        PProd = (PProd_FG + PProd_AST + FT)*(1 - (tmORB/tmScPoss)*tmORBW*tmPlay) + PProd_ORB

        marg_off = PProd - 0.92*lg_ppp*TotPoss
        marg_ppw = 0.32*lg_ppg*(t['pace']/lg_pace)
        OWS = marg_off/marg_ppw

        # ----- Win Shares: defensive -----
        DORp = op['off']/(op['off'] + tm['def'])
        DFGp = op['fgm']/op['fga']
        FMwt = (DFGp*(1-DORp)) / (DFGp*(1-DORp) + (1-DFGp)*DORp)
        Stops1 = STL + BLK*FMwt*(1 - 1.07*DORp) + DRB*(1-FMwt)
        Stops2 = (((op['fga']-op['fgm']-tm['blk'])/tmMP)*FMwt*(1-1.07*DORp)
                  + ((op['to']-tm['stl'])/tmMP))*MP \
                 + (PF/tm['pf'])*0.4*op['fta']*(1-(op['ftm']/op['fta']))**2
        Stops = Stops1 + Stops2
        StopP = (Stops*tmMP) / (t['oposs']*MP)
        tmDRtg = 100*op['pts']/t['oposs']
        DPtsScPoss = op['pts'] / (op['fgm'] + (1-(1-(op['ftm']/op['fta']))**2)*op['fta']*0.4)
        DRtg = tmDRtg + 0.2*(100*DPtsScPoss*(1-StopP) - tmDRtg)
        marg_def = (MP/tmMP)*t['poss']*(1.08*lg_ppp - DRtg/100)
        DWS = marg_def/marg_ppw

        WS = OWS + DWS
        tsa = FGA + 0.44*FTA
        f = (tmMP/5)/MP
        out.append(dict(
            team=c, name=p['name'], g=p['g'], gs=p['gs'], min=MP, mpg=MP/p['g'],
            pts=PTS, reb=TRB, ast=AST, stl=STL, blk=BLK, to=TOV, pf=PF, pm=p['pm'],
            fgm=FG, fga=FGA, p3m=p['p3m'], p3a=p['p3a'], p4m=p['p4m'], p4a=p['p4a'],
            ftm=FT, fta=FTA, orb=ORB, drb=DRB,
            ppg=PTS/p['g'], rpg=TRB/p['g'], apg=AST/p['g'],
            spg=STL/p['g'], bpg=BLK/p['g'], topg=TOV/p['g'],
            fgp=100*FG/FGA if FGA else None,
            p3p=100*p['p3m']/p['p3a'] if p['p3a'] else None,
            ftp=100*FT/FTA if FTA else None,
            ts=100*PTS/(2*tsa) if tsa else None,
            efg=100*ptsfg_p/(2*FGA) if FGA else None,
            usg=100*((FGA + 0.44*FTA + TOV)*f)/(tmFGA + 0.44*tmFTA + tmTOV),
            astp=100*(AST*f)/(tmFG - FG*f) if (tmFG - FG*f) > 0 else None,
            orbp=100*(ORB*f)/(tmORB + op['def']),
            drbp=100*(DRB*f)/(tm['def'] + op['off']),
            trbp=100*(TRB*f)/(tm['reb'] + op['reb']),
            stlp=100*(STL*f)/t['oposs'],
            blkp=100*(BLK*f)/(op['fga'] - op['p3a'] - op['p4a'])
                 if (op['fga']-op['p3a']-op['p4a']) > 0 else None,
            tovp=100*TOV/(FGA + 0.44*FTA + TOV) if (FGA+0.44*FTA+TOV) > 0 else None,
            uper=uPER, aper=aPER,
            ows=OWS, dws=DWS, ws=WS, ws48=48*WS/MP,
            ortg_i=100*PProd/TotPoss if TotPoss > 0 else None, drtg_i=DRtg,
            pm100=100*p['pm']/(t['poss']*MP/(tmMP/5)),
        ))

    # normalise PER so the minute-weighted league mean is exactly 15
    lg_aper = sum(r['aper']*r['min'] for r in out) / sum(r['min'] for r in out)
    for r in out:
        r['per'] = r['aper'] * (15/lg_aper)

    return {'teams': T, 'league': L, 'players': out, 'lg_aper': lg_aper}


if __name__ == '__main__':
    import sys
    for which in sys.argv[1:]:
        s = json.load(open('season_%s.json' % which, encoding='utf-8'))
        m = build(s)
        P, T = m['players'], m['teams']
        wmean = sum(r['per']*r['min'] for r in P)/sum(r['min'] for r in P)
        print('== %s ==' % s['label'])
        print('  league pace %.1f | PPP %.3f | players %d | PER league mean %.3f (target 15)'
              % (m['league']['pace'], m['league']['ppp'], len(P), wmean))
        print('  %-4s %3s %3s   %7s %7s   %s' % ('TM','W','L','sumWS','wins','diff'))
        tot_ws = tot_w = 0
        for c in sorted(T, key=lambda c: -T[c]['w']):
            ws = sum(r['ws'] for r in P if r['team'] == c)
            tot_ws += ws; tot_w += T[c]['w']
            print('  %-4s %3d %3d   %7.2f %7d   %+5.2f' % (c, T[c]['w'], T[c]['l'], ws, T[c]['w'], ws-T[c]['w']))
        print('  TOTAL sumWS %.2f vs wins %d  (WS should track wins)' % (tot_ws, tot_w))
