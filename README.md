# India Stock Trader

An Indian NSE/BSE cash-equity adaptation of [Jake Schincariol's day-trader skill pack](https://github.com/Jakeschincariol/day-trader-skill). It provides daily chart screens, opening-range entry checks, stop/target planning, historical replay, the original Time Machine simulation, exchange-news research, INR sizing and risk checks.

The implementation uses Python's standard library. It is a research tool: it does not connect to a broker or place orders. There is no trained prediction model, strategy optimizer or guarantee of profitable trades.

## What is included

| Workflow | Commands | Indian adaptation |
| --- | --- | --- |
| Chart scanner | `universe`, `daily`; `extensions.py orb` | NSE/BSE identity, INR prices, original daily setup rules |
| News monitor | `news`; `extensions.py moves` | NSE/BSE feeds and primary filing research |
| Entry timer | `entry`; `watchlist`, `entry-replay` extensions | Completed 1/5-minute bars and verified IST sessions |
| Exit planner | `exit`; `plan` extension | Security-specific tick rounding, range midpoint/low and other original stop rules, R targets |
| Time Machine | `timemachine`, `backtest`, `chart` | Original historical ORB replay and empirical Monte Carlo sampling |
| Budget manager | `budget`, `allocate` | INR budgets, whole-share sizing and explicit account limits |
| Risk checks | `risk`; `risk-batch` extension | Quote/account freshness, exposure, loss, session and restriction checks |
| Ticket preview | `paper show`, `paper log` | Read-only proposed tickets and explicitly selected simulation logs |
| Alerts | `alerts`, `quote` | Saved research rules and state, evaluated when invoked |
| Earnings analyst | `analyst`; `xbrl` extension | Indian financial periods, verified Ind-AS mappings and INR units |
| Public disclosures | `disclosures`, `news`; `disclosure-csv` extension | Insider, promoter, shareholding, pledge, bulk/block-deal records |

The public-disclosure workflow replaces the upstream US congressional-disclosure workflow with Indian public filings. It does not claim that an equivalent Indian politician-trading feed exists.

See [command/input contracts](references/commands.md), [batch/data adapters](references/extensions.md), [Indian sources](references/india-markets.md) and the [original-parity audit](references/PARITY-AUDIT.md).

## Requirements and installation

- Python 3.10 or newer is recommended; the CLI examples were checked with Python 3.13. No `pip install` step or third-party Python package is required.
- Git for cloning this repository.
- Network access for public Yahoo Finance and exchange sources. Offline inputs are supported for reproducible research.
- Codex is optional for the Python CLI and required for the conversational skill experience.

For a new user-level Codex installation, clone the repository under your user's `.agents/skills` directory. This location and explicit `$skill-name` invocation follow the [official OpenAI skills documentation](https://learn.chatgpt.com/docs/build-skills). If the destination already exists, inspect that installation rather than cloning over it.

**Windows PowerShell**

```powershell
$SkillRoot = Join-Path $HOME '.agents/skills/india-stock-trader'
New-Item -ItemType Directory -Force (Split-Path $SkillRoot) | Out-Null
git clone https://github.com/gowreemanohar/india-stock-trader.git $SkillRoot
python -B (Join-Path $SkillRoot 'scripts/pack.py') --help
```

**macOS/Linux shell**

```bash
SKILL_ROOT="$HOME/.agents/skills/india-stock-trader"
mkdir -p "$(dirname "$SKILL_ROOT")"
git clone https://github.com/gowreemanohar/india-stock-trader.git "$SKILL_ROOT"
python3 -B "$SKILL_ROOT/scripts/pack.py" --help
```

Use `python3` instead of `python` where that is your Python executable. Existing Codex installations may already have the skill under `~/.codex/skills/india-stock-trader`; point the examples at that existing folder and avoid duplicate installations with the same skill name. If a newly installed skill does not appear in Codex, restart the app and check the skill selector. Resolve script paths from the actual installed skill folder.

## Run it in Codex

Mention the skill explicitly:

```text
$india-stock-trader scan for daily setups now. Show every match with its
exchange, daily-bar date, setup and confirmation status. Report the universe,
coverage, stale data and failed requests. Save the results in the skill's runs directory.
```

For the complete research workflow:

```text
$india-stock-trader run the full workflow on the daily-scan matches.
Check exchange news, primary filings, corporate actions, earnings and public
disclosures. Verify the applicable security master, session, tick size and restrictions.
Confirm entries using completed five-minute bars and a 15-minute opening range.
For valid entries, calculate the opening-range-midpoint stop, 2R target and
15:00 IST exit within the verified session. Mark waiting, unconfirmed, earlier
and expired signals clearly. Assess historical sufficiency independently of
current entries, run historical ORB replay where inputs permit, and run Time
Machine with 10000 paths only when at least 20 complete prior same-regime
sessions and a valid plan exist. Show the stock watchlist even when individual
trade plans remain blocked. Save timestamped results and state coverage honestly.
Use only this standalone skill and explicitly supplied inputs.
```

Specify the stocks or the intended universe when needed. The default generic skill workflow can use a bounded sample. Asking for a complete exchange universe requires the agent to assemble and validate that universe, process all batches and report gaps; it is not a single automatic all-NSE/all-BSE command.

The repository does not install a scheduled job. Recurring runs require a separately configured host automation. Alert checks are single evaluations unless a bounded foreground watch was explicitly requested.

## Quick CLI scan

These PowerShell examples keep output in a new timestamped standalone run folder. They assume `$SkillRoot` points to your installation:

```powershell
$Pack = Join-Path $SkillRoot 'scripts/pack.py'
$Run = Join-Path $SkillRoot ('runs/manual-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $Run | Out-Null

python -B $Pack daily --symbols 'RELIANCE.NS,TCS.NS' --output (Join-Path $Run 'daily.json')
python -B $Pack news --feed nse-announcements --query 'Reliance Industries,Tata Consultancy Services' --output (Join-Path $Run 'news.json')
```

The symbols above demonstrate syntax; they are not stock recommendations. Daily screening preserves the original 20-day breakout, bull-flag, 20-day-average reclaim, oversold and oversold-bounce rules. A daily pattern match is a watchlist candidate, not an intraday entry confirmation. The current daily bar is excluded unless its completion is established by a verified calendar.

### NSE and BSE coverage

```powershell
python -B $Pack universe --output (Join-Path $Run 'nse-candidates.json')
python -B $Pack daily --universe (Join-Path $Run 'nse-candidates.json') --offset 0 --limit 50 --output (Join-Path $Run 'daily-batch-0000.json')
```

`universe` automatically reads the official NSE equity CSV but currently selects **EQ-series, market-lot-one rows only**. This is a candidate subset, not a guarantee of every NSE mainboard ordinary equity. Review other series, non-unit lots, suspensions and instrument classifications. Trade-for-trade restrictions can make a listing unsuitable for an intraday exit even when it is an ordinary equity.

Increase `--offset` for subsequent batches until every intended candidate has a recorded result. Do not label the first 50 rows, a top-N list or an incomplete set of requests as a complete scan. Record eligible, attempted, completed, failed, unmapped, excluded and pending counts by exchange.

BSE requires a verified mapping CSV:

```csv
YAHOO SYMBOL,NAME,ISIN,STATUS,INSTRUMENT TYPE
```

Populate those columns with verified security-specific values, then import it:

```powershell
python -B $Pack universe --exchange BSE --input 'C:/standalone-inputs/verified-bse.csv' --output (Join-Path $Run 'bse-candidates.json')
```

Only `ACTIVE`/`EQUITY` rows with verified `.BO` provider symbols are accepted. Do not manufacture a Yahoo symbol from a BSE scrip code or substitute an NSE quote for a BSE listing. A full universe needs official mainboard classification, ordinary-equity filtering, BSE-only listings and mapping validation. Exclude SME platforms, ETFs, funds, debt, preference shares and other instruments outside the requested scope; preserve exclusion reasons. Track listings by exchange and group dual-listed companies by ISIN.

This pack provides adapters and batch commands; a fully automated NSE/BSE security-master, mapping and resume pipeline is not included.

## From a candidate to a trade plan

### 1. Prepare a verified calendar

Intraday commands need a calendar for the exact security and session dates. Verify exchange holidays, special sessions, continuous-session boundaries, auction participation, applicable tick size and trading restrictions from official notices/security masters. A calendar's presence does not establish that its contents are true.

A security master dated at EOD can apply to the following live session. Verify its effective date; do not reject it merely because the filename differs from the trading date, or apply filename date D blindly to session D. NSE illustrates prior-EOD master usage in [CMTR75401, pages 3–4](https://nsearchives.nseindia.com/content/circulars/CMTR75401.pdf).

The input CSV contract is `date,open,end,tick_size,closed`. `end` means the end of continuous trading, excluding auctions. Include source-backed closed dates where known; missing dates remain unknown. After preparing the CSV, use `calendar-build` with actual source and verification values:

```powershell
python -B $Pack calendar-build --help
```

An illustrative JSON shape is shown below. Placeholders are deliberately not executable market facts:

```json
{
  "symbol": "RELIANCE.NS",
  "timezone": "Asia/Kolkata",
  "source_url": "VERIFIED_OFFICIAL_SOURCE_URL",
  "verified_at": "VERIFIED_ISO_TIMESTAMP",
  "sessions": {
    "YYYY-MM-DD": {"open": "VERIFIED_HH:MM", "end": "VERIFIED_HH:MM", "tick_size": "VERIFIED_INR_TICK"}
  }
}
```

Historical manifests must verify the applicable security data for every historical session, including changes in tick size and session regime. Do not fill a calendar with assumed weekdays.

### 2. Confirm the entry and calculate exits

Set `$Calendar` to your verified manifest's absolute path:

```powershell
$Calendar = 'C:/standalone-inputs/RELIANCE-calendar.json'
python -B $Pack entry --symbol RELIANCE.NS --calendar $Calendar --interval 5 --or-minutes 15 --output (Join-Path $Run 'entry.json')
```

Inspect the result before continuing. The opening range is the first 15 minutes of the verified continuous session. Confirmation uses completed contiguous bars. At the instant the range finishes, a later completed breakout candle might not exist yet.

Only after a valid entry exists:

```powershell
python -B $Pack exit --entry-json (Join-Path $Run 'entry.json') --stop or-mid --target 2R --flat-by 15:00 --output (Join-Path $Run 'plan.json')
```

For the long-only range-midpoint rule, the unrounded stop is `(opening high + opening low) / 2`, risk is `entry - stop`, and the target is `entry + 2 × risk`. The CLI applies the verified security tick grid. The 15:00 exit must fit inside that security's verified session; it is not an unconditional rule for every special session. An earlier or expired entry must not be presented as a fresh trade.

### 3. Replay history and run Time Machine

Download the available five-minute history:

```powershell
python -B $Pack fetch --symbol RELIANCE.NS --interval 5m --history --output (Join-Path $Run 'history.json')
```

For a standalone historical replay, prepare a strategy JSON with `or_minutes`, `stop_rule`, `target_rule` and `flat_minutes_before_end`. For example, use the original 15-minute range, `or-mid`, `2R`, and a session-relative cutoff verified to match the intended exit. The correct minutes before close can differ between session regimes.

```powershell
$Strategy = 'C:/standalone-inputs/orb-strategy.json'
python -B $Pack backtest --symbol RELIANCE.NS --calendar $Calendar --strategy $Strategy --offline (Join-Path $Run 'history.json') --output (Join-Path $Run 'backtest.json')
python -B $Pack timemachine --plan (Join-Path $Run 'plan.json') --calendar $Calendar --offline (Join-Path $Run 'history.json') --replays 10000 --seed 19 --window 2 --output (Join-Path $Run 'timemachine.json')
python -B $Pack chart --input (Join-Path $Run 'timemachine.json')
```

Time Machine requires **at least 20 complete prior same-regime sessions** and a valid plan. A request for 60 days of five-minute data does not prove that 20 usable sessions were returned. Assess sufficiency independently of whether a current entry exists. Exclude incomplete sessions, future data and auction bars. Use `--before`/`--now` for an explicit historical replay clock and label retrospective examples.

Time Machine also derives the historical ORB rule from an ORB plan. Its output includes:

- `p_target`: simulated paths hitting the target before the stop and planned exit.
- `p_stop`: paths hitting the stop first; a bar touching both is treated stop-first.
- `p_neither`: paths reaching the planned exit without either level being hit.
- Original price bands, sample paths, histogram, average R and reward/risk verdict.

These are empirical simulations, not trained forecasts or fill probabilities. Original assumptions are preserved: confirmation-close historical entry, independent time-of-day resampling, no fees/slippage, and a stop touch counted as −1R even through a gap. Real fills can be worse. Current constituents and selecting past examples using today's matches introduce survivorship and selection bias. Review corporate actions before interpreting historical prices.

## Read the results correctly

| Result | Meaning |
| --- | --- |
| Daily setup | A completed daily bar meets an original screening rule |
| `range_forming` / `not_open` | The opening range or trading session is not ready |
| `waiting` | A valid session/bar check has not produced a confirming trigger |
| `triggered` | The original entry rule triggered recently, as of the result's clock |
| `triggered_earlier` | The trigger occurred earlier; it is not automatically a fresh entry |
| `expired` | The entry window has passed |
| Unconfirmed / blocked | Required data or verification is missing; this is not proof that no setup exists |
| `PASS_RESEARCH` | A proposed ticket passes supplied research checks; it never authorizes a broker order |

CLI output is JSON on stdout. `--output` creates a **new** file and refuses overwriting an existing output; use distinct names or a new run folder. Explicit `--state` updates only that chosen state file. `--offline` consumes saved inputs, and `--now` makes supported research commands reproducible.

A useful report includes the stock watchlist, setup/bar dates, current versus earlier/waiting/unconfirmed/expired status, valid entry/stop/target/exit values, news evidence, historical sufficiency, replay/simulation results, coverage and specific blockers. A previous close is not an entry price. Partial coverage and stale bars must remain visible.

## Account features, alerts and filings

Account details are **not required** to scan stocks, display a watchlist or calculate a market-based entry/exit plan. `budget`, `allocate`, `risk` and ticket previews need the relevant explicitly supplied standalone account, holdings, limits, allocation inputs and fresh quote data. Missing exposure cannot be treated as zero. Exact schemas and required fields are in [commands.md](references/commands.md).

`alerts create --plan FILE` prepares stop/target/time rules. `alerts check` evaluates explicit rules, quotes, calendar and deduplication state once; it does not establish continuous monitoring or a fill. `paper show/log` only reads selected ticket/log inputs.

Exchange RSS summaries are leads. Read material primary documents, distinguish event and filing dates, and do not interpret an empty recent feed as no filings. `analyst` and the XBRL adapter require verified financial scope, context, taxonomy and INR units; PDF-only filings need verified extraction. Public-disclosure amounts, actors, dates and unknown values must be preserved.

## Privacy and operational boundaries

- Use this skill's standalone inputs and `runs/` directory. Do not discover or reuse unrelated projects, portfolios, environment files or credentials.
- Public HTTPS requests disclose requested symbols and the client's IP to the provider. The runtime does not upload local account documents.
- Quotes and bars can be delayed, missing, stale or rate-limited. Respect providers, use bounded batches, cache unchanged data and report failed requests.
- Local run output, account inputs, holdings, limits, quotes and alert state can contain personal information. Keep them out of source-control uploads.
- No broker integration, account mutation, order/fill/flatten actions, new prediction model or automatic scheduling is provided.

## Tests and repository layout

Run the offline Python unit tests from the skill directory:

```powershell
python -B -m unittest discover -s scripts -p 'test_*.py'
```

Direct upstream comparison tests can skip when a separate original `trader-timemachine` installation is unavailable; normal runtime does not depend on that installation. Tests validate implementation behavior and original parity, not a profitable trading edge.

```text
SKILL.md       Agent instructions and workflow routing
scripts/       Standalone Python commands and offline tests
references/    Input contracts, Indian sources and parity/provenance notes
README.md      Installation and usage
LICENSE        MIT license and upstream attribution
runs/          Local research output; not distributed with source
```

## Attribution and license

Derived from [Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill). The original Time Machine mathematics are retained in `scripts/upstream_simulation.py` with attribution. Indian market/session/currency/filing adapters and the research-only boundaries are documented in [PARITY-AUDIT.md](references/PARITY-AUDIT.md).

Distributed under the [MIT License](LICENSE), retaining Jake Schincariol's copyright notice. This project is not affiliated with NSE, BSE, Yahoo Finance or a broker.
