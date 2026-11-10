# Scope correction: Indian adaptation only

Checked 2026-11-01 against all eleven installed original skills. Source inventory: [original-inventory.json](original-inventory.json), 27 Python/instruction/example files with hashes, command/argument/function inventories. Upstream: https://github.com/Jakeschincariol/day-trader-skill . The installed originals include explicit Codex safety restrictions; those restrictions remain the baseline. In particular, `trader-broker/SKILL.md` permits only show/log and disables approval, result, fill and flatten actions. Upstream's broader broker integration is not silently re-enabled.

## Corrections made in this pass

- Removed walk-forward scoring and chronological holdout reports: absent from the original.
- Removed added profit-factor, drawdown and confidence-interval analytics.
- Removed paper init/fill/close/flatten and their implementation functions; retained read-only preview/log as instructed by the installed original.
- Removed the added transaction-cost/slippage simulation and duplicate legacy sizing command. Nonzero old cost settings fail explicitly, rather than being silently ignored.
- Restored confirmation-close historical entries, stop-first checking and original -1R stop treatment including gaps. The former next-open/gap-fill changes were strategy changes, not localization.
- Copied the original Time Machine's pure mathematical functions into `upstream_simulation.py`, retaining MIT attribution. The only change to `simulate` is making fixed US session length an argument for Indian sessions.
- Restored original random slot selection, random draw order, percentile definition, independent 2,000-path fan, five percentile bands, 160 sample paths, 24-bin 1–99% histogram, reward/risk verdict and qualifying notes.
- Restored original flat-series RSI behavior (100). The earlier neutral-50 correction changed upstream behavior and was removed.
- Restored automatic historical ORB replay as part of Time Machine; no separate strategy file is required for an ORB plan.
- Filled original feature gaps: annual-minus-three-quarters Q4 derivation, latest restatement selection, optional daily order count and adding a custom alert rule.
- Trained prediction models remain removed. None exists in the original.

## Eleven-workflow mapping

| Original | Indian implementation | Required market/runtime substitution |
| --- | --- | --- |
| scanner | pack universe/daily; extensions orb | NSE equity list/BSE mapped import, suffixes, INR and verified Indian sessions; chart requests replace US spark batching |
| news | pack news; extensions moves | Exchange feeds replace SEC feeds; company-name filters where feeds omit symbols |
| entry | pack entry; extensions watchlist/entry-replay | IST, security calendar, 1/5-minute completed bars, same range/level/volume logic |
| exit | pack exit; extensions plan | Indian tick size and explicit flat-by time; same long-only range/price/pct/ATR stops and R/price targets |
| timemachine | pack timemachine/backtest/chart | Copied original mathematics with variable verified Indian session length |
| budget | pack budget/allocate | Whole shares, INR limits, cash/position/order/loss bounds |
| risk | pack risk; extensions risk-batch | Indian eligibility/session checks replace US PDT/calendar; cumulative explicit batch reservations |
| broker | pack paper show/log | Read-only safety boundary of installed original retained; no external actions |
| alerts | pack alerts/quote | IST session clock, same threshold/time/percentage/opening rules and state |
| analyst | pack analyst/news results; extensions xbrl | Indian source URLs, taxonomy/context selection, INR/lakh/crore, discrete-quarter and derived-Q4 handling |
| pelosi | pack disclosures/news insider feeds; extensions disclosure-csv | Indian insider/promoter/pledge/shareholding/bulk/block disclosures replace US House/Senate reports; do not fabricate a politician feed |

## Fidelity tests

`test_original_parity.py` compares the copied Monte Carlo implementation directly against the original pure function for 12-, 72- and 78-bar sessions with two seeds. Entire results must match, including probabilities, paths, bands and histograms. Historical entries/outcomes are compared against original `history_replay`. A complete offline Time Machine run checks 10,000 replays and automatic history. Original-source comparison tests are optional when the original installation is unavailable; runtime does not depend on it.

Scope fidelity is not a claim of identical CLI flags or identical data providers. Indian primary sources do not expose a universal SEC companyfacts/House PTR equivalent. XBRL needs verified tag/context mapping; PDF-only sources need verified extraction. Calendar/tick manifests must reflect actual notices, not invented weekdays. Those provider differences are explicit, not hidden behind claims of automatic coverage.
