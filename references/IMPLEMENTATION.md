# Current installation record

The standalone skill is installed in the directory containing `SKILL.md`; its location depends on the user's skill installation path.

Purpose: adapt the eleven original day-trader workflows to Indian equities, with no trained prediction model or extra strategy/evaluation engines. See [PARITY-AUDIT.md](PARITY-AUDIT.md) for corrections, exact mapping and unavoidable provider differences; [commands.md](commands.md) and [extensions.md](extensions.md) describe current commands.

Source: Jakeschincariol/day-trader-skill (MIT). Original scanner `rsi`/`find_setups` were copied with original semantics. `upstream_simulation.py` copies seven original pure Time Machine functions. `simulate` accepts the session bar count instead of assuming 78 US bars. License and attribution are retained. Source inventory/provenance files record origins. No user custom project has been used; originals remain unchanged.

Earlier validation JSON files are historical records. Some describe capabilities subsequently removed (trained models, walk-forward scoring, extra fill/cost analytics). Current validation is `validation-parity.json`; current instructions and source are authoritative. The prior trained model artifact and executable are absent.

No packages, credentials or brokerage connectors were installed. Research tools use explicit inputs/public allowlisted endpoints. Tests use synthetic data; comparison tests load only selected inspected pure mathematical functions from the installed original. This is implementation verification, not a comprehensive security audit or evidence of profitable trading.
