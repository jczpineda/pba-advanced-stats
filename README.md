# PBA Advanced Stats

Advanced basketball metrics for the Philippine Basketball Association's 50th season,
built from the league's own public match feed: **177 games, two conferences, 13 teams,
444 player-seasons.**

PER, Win Shares, four factors, true shooting, usage and the rest — plus a worked
play-by-play breakdown of a single game.

It also **does not** ship BPM or VORP, and the reason is the most interesting thing here.

---

## The short version

Two of the four metrics I set out to build didn't survive contact with the data.

**PER and Win Shares did.** Win Shares come with a built-in external test: a team's
Win Shares should add up to roughly its actual wins. They do.

| Conference | Summed Win Shares | Actual wins |
|---|---|---|
| Governors' Cup | 73.7 | 74 |
| Commissioner's Cup | 102.4 | 103 |

**BPM and VORP didn't.** BPM 2.0 can't be reproduced from a public box-score feed —
its published method needs shooting-location data the feed doesn't carry, plus
position and offensive-role coefficients that were never published. So I fit a
BPM-shaped model on the league's own plus-minus instead: 339 player-seasons, ridge
regression, cross-validated with folds **grouped by team** so the model couldn't score
well merely by learning which players were on good teams.

It came back with a cross-validated R² of **0.17**, and coefficients claiming that
committing fouls helps your team (+0.85 points per 100) and that three-point shooting
hurts it (−0.27).

That's not a model, it's noise with a leaderboard. Publishing it would have put an
authoritative-looking number next to real players' names, so the dashboard states
what's missing and why, in the place you'd go looking for it.

You can reproduce that rejection yourself:

```bash
python src/bpm_experiment.py
```

---

## Quickstart

Requires Python 3.9+.

```bash
pip install -r requirements.txt

python run.py --fetch      # scrape the feed (1 request/sec, ~3 min), then build
python run.py              # rebuild from cached pages, no network at all
```

Then open `dist/dashboard.html`.

`data/raw/` is gitignored, so a fresh clone needs `--fetch` once. After that every
rebuild is offline — pages already on disk are never re-requested.

```bash
python run.py --smoke      # 3 games per conference, to check the pipeline works
```

---

## Where the data comes from

`pba.ph/recap?match=NNN` is client-rendered: fetching it returns navigation and a
footer, no statistics. The numbers live in an iframe on a separate host which serves
**fully static HTML** — box scores, team comparison and the complete play-by-play are
all in the markup. No browser automation, no JavaScript execution, no private API.

Game IDs are sequential and each conference's index page links every game in it, so
the ID lists in `data/ids/` were harvested with a regex over two pages.

---

## Validation is the point

Any scraper can produce numbers. The question is whether they're the right ones, and
the failure mode that matters is a parser that returns *plausible* output rather than
no output.

Every game must pass three independent checks before it enters the dataset:

1. The running score, rebuilt from scoring events, matches **every scoreline printed
   in the page** (90–130 checkpoints per game).
2. That same rebuild matches the **official quarter table** at every period end.
3. Player points **sum to the final score**.

A game failing any check is skipped, never patched. All 177 pass.

That gate earned its keep immediately. The two conferences use **different
play-by-play dialects** — the older one tags misses with `MISS` and leaves made field
goals unmarked, writes `(X Assist)` instead of `(AST: X)`, and `Sub: X for Y` instead
of `SUB: X in for Y`. The CSS class names are identical in both, so the difference is
invisible until you read the text. The first run scored all 103 Commissioner's Cup
games 0–0. Without check 3, that would have been a silent, conference-sized hole in
the dataset.

Two further traps the checks caught:

- **The running score is printed on only one team's baskets.** Forward-filling it
  leaves the other team's line permanently lagging — at one point showing a halftime
  score of 33–35 when it was really 33–42. The score is reconstructed from scoring
  events instead, with the printed scorelines used purely as checkpoints.
- **A player's share of team possessions is not his share of total player-minutes.**
  Getting that wrong inflates every per-100 rate by exactly 5×, which is enough to
  look wrong but not obviously wrong.

---

## What's deliberately missing

Run `python src/lineup_check.py 601` to see the second one fail on purpose.

| Not published | Why |
|---|---|
| **BPM, VORP** | BPM 2.0 isn't reproducible from this feed; a refit on the league's own plus-minus reached CV R² 0.17 with coefficients that contradict basketball. See above. |
| **Lineup on/off, five-man data** | The feed logs many substitutions but omits others. A reconstructed lineup disagrees with official minutes for 8 of 25 players in one checked game — one by 22 minutes. The official box plus-minus is internally consistent (it sums to exactly 5× the final margin for both teams), so the box is right and the sub log is incomplete. |

Sample size is flagged rather than hidden: conferences run 10–27 games per team, so
leaderboards require at least half a team's games *and* 15+ minutes per game, and
players below that line are dimmed rather than dropped.

---

## PBA-specific details

- **The 4-point line.** The 50th season has one. PER's bonus-point term is adapted
  from `3PM` to `3PM + 2×4PM`, and effective field-goal percentage is generalised to
  `points from field goals / (2 × FGA)`, which reduces to the standard formula when
  nobody attempts a four.
- **12-minute quarters, 5-minute overtimes.** 10 of the 177 games went to overtime;
  team minutes scale accordingly.
- **Import conferences.** Both the Commissioner's and Governors' Cup allow imports,
  who dominate the usage and scoring leaderboards. Baselines are computed **per
  conference**, never pooled, because the two are different competitive environments.

---

## Repo layout

```
run.py                      one-command pipeline
src/
  paths.py                  project paths and conference config
  fetch.py                  polite scraper: 1 req/sec, cache-first
  pba_parse.py              one game page -> structured data (handles both dialects)
  game_detail.py            single-game analytics; works for any game id
  build_league.py           season aggregation + the three validation checks
  metrics.py                PER and Win Shares
  build_dashboard.py        assembles league.json and injects it into the template
  bpm_experiment.py         the BPM refit that was tried and rejected
  lineup_check.py           demonstrates why lineup data isn't published
template/dashboard.html     single-file dashboard, __LEAGUE__ placeholder for the data
dist/dashboard.html         the built output
data/raw/                   scraped pages (gitignored, ~98 MB)
data/derived/               season_*.json, league.json (gitignored, regenerable)
```

The dashboard is a single self-contained HTML file: no build step, no framework, no
runtime dependencies. Charts are hand-drawn SVG.

---

## A note on the data

The statistics belong to the PBA. This repository contains **code, not data** — the
scraped pages and everything derived from them are gitignored, so a clone fetches its
own copy from the public feed.

Neither host publishes crawl rules (`pba-api01.actech2.com/robots.txt` returns 404;
`pba.ph/robots.txt` returns the homepage), which is permissive by default rather than
permission. The scraper is deliberately gentle — one request per second, cache-first,
177 requests total — but if you intend to run this continuously or at larger scale,
ask the PBA first. This is a personal analytics project and isn't affiliated with or
endorsed by the PBA.

---

## Licence

Code is MIT (see `LICENSE`). The underlying statistics are not mine to license.
