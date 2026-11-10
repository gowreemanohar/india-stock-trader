# Indian market inputs and sources

Recheck rules for the requested trading date:

- NSE sessions/holidays: https://www.nseindia.com/resources/exchange-communication-holidays
- NSE closing-auction applicability: https://www.nseindia.com/market-data/closing-auction-session
- NSE official RSS directory: https://www.nseindia.com/static/rss-feed
- NSE announcements: https://www.nseindia.com/companies-listing/corporate-filings-announcements
- NSE results: https://www.nseindia.com/companies-listing/corporate-filings-financial-results
- BSE notices and filings: https://www.bseindia.com/
- SEBI: https://www.sebi.gov.in/

Verify symbol/ISIN, equity status, venue, tick size, auction eligibility and date-specific continuous trading. Normal opening is generally 09:15 IST, but never assume all dates/securities share one close. Verify holidays, Muhurat, weekend sessions, halts and historical changes. A supplied manifest is not automatically source-verified. If unavailable, report the limitation rather than fabricate an intraday judgment.

Indian filings replace US-specific sources. Read actual documents; RSS titles are leads. Preserve transaction/filing dates, actor, category and declared amounts. Indian promoter/insider/shareholding information is not an equivalent real-time politician-trading feed. Never imply that empty recent feeds prove no transactions.

Compare financial scope, units, fiscal periods and restatements. EPS remains INR per share. Analyst accepts discrete quarters and annual periods; Q4 is derived only from a complete contiguous Q1–Q3 set and annual totals, labeled derived. XBRL tag/context mapping must match the filing. Verify PDF extraction before entering numbers.

Check liquidity, spread, circuits, surveillance/trade-to-trade restrictions, suspension, corporate events and broker square-off deadlines when interpreting plans. INR risk sizing is arithmetic, not a guarantee. Costs and gaps matter in reality, but the original simulation does not model them; disclose that limitation without adding a different strategy engine.

The original Time Machine models confirmation-close entry, stop-before-target intrabar order, -1R stop touches even through gaps, and independent time-of-day resampling. Preserve these assumptions. Do not call them accurate fill predictions. Current constituents used historically have survivorship bias; review corporate actions and historical coverage.

Alerts are single-shot checks unless the user explicitly requests monitoring through a supported tool. A crossing can occur between checks. Never infer broker fills from alerts or connect a broker under this skill.
