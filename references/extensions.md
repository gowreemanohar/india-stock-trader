# Indian data and batch adapters

Replace `<skill-directory>` with the directory containing this skill's `SKILL.md`. Base: `python -B "<skill-directory>/scripts/extensions.py" ACTION --help`.
Use explicit absolute input/output paths. These commands expose original workflows through Indian data contracts, not extra strategies.

- `orb` / `watchlist --input FILE [--offline FILE --now ISO --offset N --limit N]`: input `{"items":[{"symbol":"RELIANCE.NS","calendar":{...}}]}`. Calendar follows commands.md. Optional range, level, volume multiplier and entry-window fields. Batches at most 50; partial coverage/errors are reported.
- `entry-replay --input FILE --offline FILE --now ISO`: input symbol, inline calendar, date and optional range/level/volume. Replay completed five-minute clocks of an already completed day without sleeping. Same original entry confirmation rules.
- `moves --symbols RELIANCE.NS,TCS.NS [--move-pct 3 --offline FILE]`: quote versus its preceding trading session close, with timestamp/age. A price move is not a claimed news cause.
- `plan --input FILE`: explicit hypothetical entry document in india-entry-v2 shape, stop_rule, target_rule and flat_by. ATR uses pack exit with bars instead. Same original stop/target rules.
- `risk-batch --input FILE --calendars FILE`: input tickets array, limits, account, quotes mapping; calendar file maps symbol to verified manifest. Reserve accepted ticket cash/risk/exposure and trade/order counts before evaluating the next. Projection is not a broker fill or a mutable paper account.
- `paper-log --input FILE`: inspect events/positions/cash from an explicitly selected simulation log; no mutation.
- `xbrl --mapping FILE --input XBRL` or `--url EXCHANGE_URL`: mapping includes symbol, scope, filed_at, source_url, context_ids and metrics mapping output names to expanded XML tags. Verify taxonomy/context/consolidation against the actual filing. INR and INR/share units enforced; decimals is precision, not scaling. Output passes through analyst quarterly/restatement logic. XML only, not PDF or arbitrary iXBRL HTML. Entity declarations rejected.
- `disclosure-csv --input CSV --mapping JSON`: columns maps normalized disclosure fields to headers; constants supplies fixed symbol/category/source fields where appropriate. Uses disclosure validation and reporting-delay calculations.

The original SEC/House formats cannot simply be renamed to Indian formats. Official Indian sources and verified mappings are necessary. PDF-only reports require accurate extraction before structured analysis. Do not invent data to conceal a missing feed or mapping.
