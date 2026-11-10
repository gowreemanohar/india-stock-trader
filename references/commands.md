# Commands and input contracts

Replace `<skill-directory>` with the directory containing this skill's `SKILL.md`. Base: `python -B "<skill-directory>/scripts/pack.py" COMMAND --help`.

Use absolute paths in an explicitly selected standalone data directory. JSON prints to stdout. `--output FILE` creates a new file (no overwrite). Explicit `--state FILE` permits that state's update. Expanded inputs accept `.json.gz` with a 32 MiB decompressed bound. No custom project is needed.

## Scanner and data preparation

- `universe`: current official NSE EQ/lot-one list. `--exchange BSE --input CSV` imports verified `YAHOO SYMBOL,NAME,ISIN,STATUS,INSTRUMENT TYPE`; ACTIVE/EQUITY rows only. No guessed BSE provider mapping.
- `daily --symbols RELIANCE.NS,TCS.NS`: original daily closing-price setups. `--universe FILE --offset 0 --limit 50` selects a batch. `--min-price`, `--min-volume`, `--offline`, `--now` supported. `--calendar FILE` accepts a single-symbol manifest or symbol-to-manifest mapping and includes today's bar only after its verified close. Without it, today's bar is conservatively omitted. Report sample coverage, failures and last-bar date.
- `quote --symbols RELIANCE.NS`: timestamped INR quote, not guaranteed real time.
- `fetch --symbol RELIANCE.NS --interval 5m --history --output FILE`: Yahoo chart input for replay; historical request is 60 days for 5m. Availability may be less. Offline input is Yahoo chart JSON or symbol-to-chart mapping.
- `calendar-build --symbol SYMBOL --input CSV --source-url URL --verified-at ISO`: imports `date,open,end,tick_size,closed` rows.

Calendar JSON is per security:

```json
{"symbol":"RELIANCE.NS","timezone":"Asia/Kolkata","source_url":"VERIFIED_SOURCE_URL","verified_at":"VERIFIED_ISO_TIMESTAMP","sessions":{"YYYY-MM-DD":{"open":"HH:MM","end":"HH:MM","tick_size":"VERIFIED_TICK"}}}
```

Replace placeholders with verified values. Use `{"closed":true}` for known closed dates. Absent dates are unknown. End is continuous-trading end, excluding auctions. The program checks structure, not the truth of the supplied source. Never invent historical calendars.

## Entry, exit and original Time Machine

`entry --symbol SYMBOL --calendar FILE [--date DATE --offline FILE --now ISO]` supports `--interval 1|5`, `--or-minutes 15`, `--level PRICE`, `--min-volume-x`, entry windows. Completed contiguous bars only. Status distinguishes waiting, current/earlier trigger, expired, range-forming and not-open. Explicit `--watch-seconds N --poll-seconds 60` runs bounded foreground polling, never an automatic background schedule.

`exit --entry-json FILE --stop or-mid --target 2R --flat-by HH:MM`: stops or-mid/or-low/price:X/pct:X/atr:K; targets XR/price:X. ATR reads chart data (optionally `--offline`) through signal time only. The output includes INR entry/stop/target, tick, signal/session/flat timestamps, rule, range length and interval. No fee/slippage flags; compatibility fields in plans must be zero.

Strategy JSON for standalone historical replay:

```json
{"or_minutes":15,"stop_rule":"or-mid","target_rule":"2R","flat_minutes_before_end":5}
```

- `backtest --symbol SYMBOL --calendar FILE --strategy FILE [--offline FILE --before DATE --now ISO]`: exposes the original history replay independently. Range midpoint/low or pct:X stops, XR target. Entry is first confirming close, stop checked first; reports target/stop/close counts, green count and average R. No added drawdown, holdout or profitability analytics.
- `timemachine --plan FILE --calendar FILE [--offline FILE --now ISO] --replays 10000 --seed 19 --window 2`: copied original resampling. Historical ORB replay derives its rule automatically from the plan; optional `--strategy FILE` can explicitly supply it. At least 20 prior complete same-regime sessions. Output keys p_target, p_stop, p_neither, p_green, avg_R, price percentiles, five-band fan, 160 sample paths, histogram, verdict and notes. Default replay cutoff comes from plan flat_by.
- `chart --input FILE`: original five-band simulation represented as a compact text chart.

No trained model or walk-forward scoring command exists. Original simulation assumptions are intentionally retained: no fees/slippage and stop touch gives -1R even on a gap; real losses can exceed that.

## Sizing and risk

Limits require max_order, min_order, max_position, cash_buffer, max_loss_per_trade, max_daily_loss, min_reward_risk, max_trades_per_day, max_quote_age_seconds, max_account_age_seconds, no_entries_before/after (HH:MM), optional blocked_symbols and max_orders_per_day. All monetary values are INR and must come from the user, not fabricated defaults.

Account: cash, positions mapping symbol to quantity and market_value, as_of ISO, realized_loss_today (positive loss), open_risk, trades_today, entered_symbols_today, and orders_today when an order-count limit is used.

Quote: symbol, currency INR, price, quoted_at ISO, restrictions_checked true only after actual security-restriction verification.

- `budget --plan FILE --limits FILE --account FILE`: whole-share proposed paper ticket constrained by cash, order/position cap and stop loss. No fee/slippage extension.
- `allocate --input FILE`: weights/prices mappings, cash, position_cap, optional cash_buffer. Pass the selected subset to implement top-N; leftover cash is explicit.
- `risk --ticket FILE --limits FILE --account FILE --quote FILE --calendar FILE [--now ISO]`: recompute bounds, freshness, daily/open risk, duplicates, session/tick and restrictions. Returns PASS_RESEARCH or BLOCK, not execution approval.
- `paper show --ticket FILE`: read-only draft ticket and fingerprint.
- `paper log --ledger FILE`: read-only events from explicit mode=paper simulation log. No init/fill/close/flatten/approve/result commands, consistent with the installed original's restriction.

## Alerts

`alerts create --plan FILE` produces stop/target/flat rules. `alerts add --rules FILE --rule FILE` adds a unique-ID rule, returning new rules. `alerts list`, `alerts reset --reset-id ID --state FILE`, `alerts clock --calendar FILE --symbol SYMBOL`.

`alerts check --rules FILE --quotes FILE --calendar FILE --symbol SYMBOL --state FILE [--now ISO]`: quotes map symbol to the shape above. Rules: id, symbol, optional date; above/below with price; pct_move with reference/pct/direction; time with ISO at; opening_bell. Above/below can rearm. All rules in a batch must match the calendar symbol. Time-only checks need no quotes. Stale data is an error, not a fabricated alert.

## News, earnings and disclosures

`news --feed NAME [--query "Company name,SYMBOL" --since ISO --offline RSS --state FILE --new-only]`. Feeds: nse-announcements/results/integrated-financials/insiders/shareholding/encumbrance/board/actions, bse-announcements/insiders. Use actual company names where feeds omit ticker symbols. Read primary documents; feeds cover recent windows only.

`analyst --input FILE`: symbol, scope (consolidated/standalone), periods array. Period fields: start/end, filed_at, source_url, unit (INR/lakh/crore/million_inr), revenue; optional operating_profit, pat, operating_cash_flow, debt, cash, exceptional_items, eps. EPS stays INR/share. Latest filed revision wins for an identical period. Discrete 70–100 day quarters and full 350–380 day years are supported; Q4 derives from annual minus contiguous Q1–Q3 and is labeled with sources. Nonpositive prior values yield no percentage-growth claim.

`disclosures --input FILE [--state FILE]`: records have symbol, category (insider/promoter/shareholding/pledge/bulk_deal/block_deal), person_or_entity, event_date, filed_at, source_url, optional quantity/value_inr/holding_percent/pledged_percent. Transaction details are preserved; unknown values stay unknown. This is the Indian disclosure replacement, not a politician-prediction feature.
