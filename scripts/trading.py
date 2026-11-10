"""Entry, exit, budget, portfolio risk, paper tickets and alert evaluation."""
import datetime as dt
from decimal import Decimal
import statistics

from pack_core import (number, integer, symbol, fingerprint, now_ist, session_bars,
                       tick_price, validate_plan, clock)


def entry_check(sym, bars, calendar, now, day=None, interval=5, or_minutes=15,
                level=None, min_volume_x=0, no_entries_before=None, no_entries_after=None):
    sym = symbol(sym)
    day = day or now.date().isoformat()
    spec = calendar.get(day)
    if interval not in (1, 5) or or_minutes < interval or or_minutes % interval:
        raise ValueError('Opening range must be a multiple of the 1- or 5-minute interval.')
    volume_x = float(number(min_volume_x))
    before = clock(day, no_entries_before) if no_entries_before else spec['start'] + dt.timedelta(minutes=or_minutes)
    after = clock(day, no_entries_after) if no_entries_after else spec['end'] - dt.timedelta(minutes=interval)
    if not spec['start'] <= before < after < spec['end']:
        raise ValueError('Entry window must be within the verified session and leave a bar to trade.')
    result = {'schema': 'india-entry-v2', 'symbol': sym, 'as_of': now.isoformat(), 'interval_minutes': interval,
              'session_open': spec['start'].isoformat(), 'session_end': spec['end'].isoformat(),
              'tick_size': str(spec['tick']), 'or_minutes': or_minutes, 'setup': 'level' if level is not None else 'orb'}
    if now < spec['start']:
        return dict(result, status='not_open')
    complete = session_bars(bars, spec, now, interval)
    n = or_minutes // interval
    if len(complete) < n:
        return dict(result, status='range_forming')
    high = max(b['high'] for b in complete[:n])
    low = min(b['low'] for b in complete[:n])
    threshold = float(number(level, positive=True)) if level is not None else high
    avg_volume = statistics.mean(b['volume'] for b in complete[:n])
    hit = next((b for b in complete[n:] if before <= b['start'] + dt.timedelta(minutes=interval) <= after
                and b['close'] > threshold and b['volume'] >= volume_x * avg_volume), None)
    result.update(opening_high=high, opening_low=low, level=threshold, last_close=complete[-1]['close'],
                  last_completed_at=(complete[-1]['start'] + dt.timedelta(minutes=interval)).isoformat())
    if hit:
        at = hit['start'] + dt.timedelta(minutes=interval)
        status = 'expired' if now > after else ('triggered' if now - at <= dt.timedelta(minutes=interval) else 'triggered_earlier')
        result.update(status=status, entry_at=at.isoformat(), price=hit['close'],
                      trigger_age_seconds=int((now - at).total_seconds()), volume_ratio=hit['volume'] / avg_volume if avg_volume else None)
    else:
        result['status'] = 'expired' if now > after else 'waiting'
    return result


def atr(bars, period=14):
    if not bars:
        raise ValueError('ATR needs completed bars before entry.')
    ranges = [b['high'] - b['low'] if i == 0 else max(b['high'] - b['low'], abs(b['high'] - bars[i-1]['close']),
              abs(b['low'] - bars[i-1]['close'])) for i, b in enumerate(bars)]
    n = min(period, len(ranges))
    value = sum(ranges[:n]) / n
    for r in ranges[n:]:
        value = (value * (period - 1) + r) / period
    return value, n


def exit_plan(entry_doc, stop_rule, target_rule, flat_by, costs=0, slippage_bps=0, bars=None, min_stop_pct=0.05):
    if number(costs) or number(slippage_bps):
        raise ValueError('Original-pack parity: the added cost/slippage model has been removed.')
    if entry_doc.get('schema') != 'india-entry-v2' or 'entry_at' not in entry_doc:
        raise ValueError('A confirmed india-entry-v2 signal is required.')
    tick = number(entry_doc['tick_size'], positive=True)
    entry = tick_price(entry_doc['price'], tick, up=True)
    high, low = number(entry_doc['opening_high'], positive=True), number(entry_doc['opening_low'], positive=True)
    if low > high:
        raise ValueError('Invalid opening range.')
    at = now_ist(entry_doc['entry_at'])
    atr_info = None
    if stop_rule == 'or-mid':
        stop = (high + low) / 2
    elif stop_rule == 'or-low':
        stop = low
    elif stop_rule.startswith('price:'):
        stop = number(stop_rule[6:], positive=True)
    elif stop_rule.startswith('pct:'):
        stop = entry * (1 - number(stop_rule[4:], positive=True) / 100)
    elif stop_rule.startswith('atr:'):
        step = dt.timedelta(minutes=integer(entry_doc['interval_minutes'], 1, 5))
        complete = [b for b in (bars or []) if now_ist(entry_doc['session_open']) <= b['start'] and b['start'] + step <= at]
        value, used = atr(complete)
        atr_info = {'atr': value, 'initial_period_bars': used, 'bars_used': len(complete)}
        stop = entry - number(stop_rule[4:], positive=True) * Decimal(str(value))
    else:
        raise ValueError('Stop rule: or-mid, or-low, price:X, pct:X or atr:X.')
    stop = tick_price(stop, tick)
    if not 0 < stop < entry or (entry - stop) / entry * 100 < number(min_stop_pct):
        raise ValueError('Stop is invalid or tighter than the stated minimum percent.')
    if target_rule.endswith('R'):
        target = entry + number(target_rule[:-1], positive=True) * (entry - stop)
    elif target_rule.startswith('price:'):
        target = number(target_rule[6:], positive=True)
    else:
        raise ValueError('Target rule: XR or price:X.')
    target = tick_price(target, tick, up=True)
    flat = clock(at.date().isoformat(), flat_by)
    slip = number(slippage_bps)
    if slip >= 10000:
        raise ValueError('Slippage must be below 10000 bps.')
    result = {'schema': 'india-plan-v2', 'symbol': symbol(entry_doc['symbol']), 'currency': 'INR', 'side': 'buy',
              'entry': str(entry), 'stop': str(stop), 'target': str(target), 'entry_at': at.isoformat(),
              'session_open': entry_doc['session_open'], 'session_end': entry_doc['session_end'], 'flat_by': flat.isoformat(),
              'tick_size': str(tick), 'cost_per_share': str(number(costs)), 'slippage_bps': str(slip),
              'stop_rule': stop_rule, 'target_rule': target_rule, 'or_minutes': entry_doc['or_minutes'],
              'setup': entry_doc['setup'], 'interval_minutes': entry_doc['interval_minutes'],
              'risk_per_share': str(entry - stop), 'reward_risk': str((target - entry) / (entry - stop)),
              'atr_info': atr_info, 'execution_enabled': False}
    validate_plan(result)
    return result


def budget(plan, limits, account):
    e, s, t = validate_plan(plan)
    cost = number(plan['cost_per_share'])
    slip = number(plan['slippage_bps']) / 10000
    worst_entry = e * (1 + slip)
    planned_risk = worst_entry - s * (1 - slip) + cost
    cash = number(account['cash']) - number(limits['cash_buffer'])
    existing = number(account.get('positions', {}).get(plan['symbol'], {}).get('market_value', 0))
    cap = min(number(limits['max_order']), number(limits['max_position']) - existing)
    qty = max(0, int(min(max(Decimal(0), cash) / (worst_entry + cost), max(Decimal(0), cap) / worst_entry,
                        number(limits['max_loss_per_trade']) / planned_risk)))
    if qty * worst_entry < number(limits['min_order']):
        qty = 0
    return {'schema': 'india-ticket-v2', 'plan': plan, 'quantity': qty, 'currency': 'INR', 'mode': 'paper',
            'notional_inr': str(qty * worst_entry), 'planned_loss_inr': str(qty * planned_risk),
            'cash_required_inr': str(qty * (worst_entry + cost)), 'status': 'sized' if qty else 'blocked_zero_shares',
            'execution_enabled': False}


def allocate(weights, prices, cash, position_cap, cash_buffer=0):
    available = number(cash) - number(cash_buffer)
    if available < 0:
        raise ValueError('Cash buffer exceeds cash.')
    cap = number(position_cap, positive=True)
    pending = {symbol(k): number(v, positive=True) for k, v in weights.items()}
    if not pending or len(pending) > 50:
        raise ValueError('Provide 1 to 50 weighted symbols.')
    allocations = {}
    remaining = available
    while pending:
        total = sum(pending.values())
        capped = [k for k in pending if remaining * pending[k] / total >= cap]
        if not capped:
            allocations.update({k: remaining * w / total for k, w in pending.items()})
            break
        for k in capped:
            allocations[k] = cap
            remaining -= cap
            del pending[k]
    rows = []
    spent = Decimal(0)
    for sym, amount in allocations.items():
        price = number(prices[sym], positive=True)
        qty = int(amount / price)
        spent += qty * price
        rows.append({'symbol': sym, 'quantity': qty, 'price_inr': str(price), 'notional_inr': str(qty * price)})
    return {'allocations': rows, 'unallocated_cash_inr': str(number(cash) - spent), 'costs_included': False, 'execution_enabled': False}


def risk_check(ticket, limits, account, quote, calendar, now):
    plan = ticket['plan']
    e, s, t = validate_plan(plan)
    qty = integer(ticket['quantity'])
    sym = symbol(plan['symbol'])
    checks = []
    def check(name, passed):
        checks.append({'check': name, 'passed': bool(passed)})
    at = now_ist(quote['quoted_at'])
    account_at = now_ist(account['as_of'])
    quote_age = (now - at).total_seconds()
    max_age = float(number(limits['max_quote_age_seconds'], positive=True))
    max_account_age = float(number(limits['max_account_age_seconds'], positive=True))
    check('fresh_same_day_quote', 0 <= quote_age <= max_age and at.date() == now.date())
    check('fresh_account_snapshot', 0 <= (now - account_at).total_seconds() <= max_account_age and account_at.date() == now.date())
    check('quote_identity_currency', quote.get('symbol') == sym and quote.get('currency') == 'INR')
    check('paper_ticket', ticket.get('mode') == 'paper' and ticket.get('schema') == 'india-ticket-v2')
    current = number(quote['price'], positive=True)
    check('setup_not_invalidated', s < current < t)
    used_entry = max(e, current) * (1 + number(plan['slippage_bps']) / 10000)
    exit_stop = s * (1 - number(plan['slippage_bps']) / 10000)
    cost = number(plan['cost_per_share'])
    per_loss = used_entry - exit_stop + cost
    risk = qty * per_loss
    reward = t * (1 - number(plan['slippage_bps']) / 10000) - used_entry - cost
    check('positive_whole_shares', qty > 0)
    check('entry_below_target', used_entry < t)
    check('minimum_reward_risk', reward / per_loss >= number(limits['min_reward_risk']))
    check('per_trade_risk', risk <= number(limits['max_loss_per_trade']))
    check('notional_bounds', number(limits['min_order']) <= qty * used_entry <= number(limits['max_order']))
    check('cash_buffer', number(account['cash']) - qty * (used_entry + cost) >= number(limits['cash_buffer']))
    existing = number(account.get('positions', {}).get(sym, {}).get('market_value', 0))
    check('position_cap', existing + qty * used_entry <= number(limits['max_position']))
    check('daily_loss_budget', number(account['realized_loss_today']) + number(account['open_risk']) + risk <= number(limits['max_daily_loss']))
    check('trade_count', integer(account['trades_today']) < integer(limits['max_trades_per_day'], 1))
    if 'max_orders_per_day' in limits:
        check('order_count', integer(account['orders_today']) < integer(limits['max_orders_per_day'],1))
    check('not_blocked', sym not in limits.get('blocked_symbols', []))
    check('not_duplicate', sym not in account.get('entered_symbols_today', []))
    status = calendar.status(now)
    check('verified_market_open', status['status'] == 'open')
    day = now.date().isoformat()
    check('entry_window', clock(day, limits['no_entries_before']) <= now <= clock(day, limits['no_entries_after']))
    check('same_day_plan_before_flat_by', now_ist(plan['entry_at']).date() == now.date() and now_ist(plan['entry_at']) <= now < now_ist(plan['flat_by']))
    if status['status'] == 'open':
        spec = calendar.get(day)
        check('calendar_plan_consistency', spec['start'] == now_ist(plan['session_open']) and spec['end'] == now_ist(plan['session_end'])
              and spec['tick'] == number(plan['tick_size']))
    check('security_restrictions_checked', quote.get('restrictions_checked') is True)
    return {'schema': 'india-risk-v2', 'status': 'PASS_RESEARCH' if all(c['passed'] for c in checks) else 'BLOCK',
            'checks': checks, 'ticket_fingerprint': fingerprint(ticket), 'as_of': now.isoformat(),
            'account_cash_inr': str(number(account['cash'])),
            'account_position_quantities': {k: integer(v['quantity']) for k, v in account.get('positions', {}).items()},
            'planned_loss_inr': str(risk), 'evaluated_entry_inr': str(used_entry), 'execution_enabled': False}






def alerts_from_plan(plan):
    validate_plan(plan)
    base = fingerprint(plan)[:16]
    common = {'symbol': plan['symbol'], 'date': now_ist(plan['entry_at']).date().isoformat()}
    return [{'id': base + '-stop', 'type': 'below', 'price': plan['stop'], **common},
            {'id': base + '-target', 'type': 'above', 'price': plan['target'], **common},
            {'id': base + '-flat', 'type': 'time', 'at': plan['flat_by'], **common}]


def evaluate_alerts(rules, quotes, calendar, now, state=None, max_age=300):
    fired, errors, updated = [], [], dict(state or {})
    today = now.date().isoformat()
    seen = set()
    for rule in rules:
        identity = rule['id']
        if identity in seen:
            raise ValueError('Duplicate alert ID.')
        seen.add(identity)
        if rule.get('date', today) != today:
            continue
        key = identity + ':' + today
        old = updated.get(key, {})
        try:
            if symbol(rule['symbol']) != calendar.symbol:
                raise ValueError('Alert and calendar symbols differ.')
            spec = calendar.get(today)
            kind = rule['type']
            if kind == 'time':
                due = now_ist(rule['at'])
                if not spec['start'] <= due <= spec['end']:
                    raise ValueError('Time alert outside verified session.')
                hit = now >= due
            elif kind == 'opening_bell':
                hit = now >= spec['start']
            else:
                q = quotes[rule['symbol']]
                at = now_ist(q['quoted_at'])
                if q.get('currency') != 'INR' or q.get('symbol') != rule['symbol'] or not 0 <= (now-at).total_seconds() <= max_age or at.date() != now.date():
                    raise ValueError('Stale or mismatched quote; price alert not evaluated.')
                if not spec['start'] <= now < spec['end']:
                    raise ValueError('Price alert outside continuous session.')
                price = number(q['price'], positive=True)
                if kind in ('above', 'below'):
                    level = number(rule['price'], positive=True)
                    hit = price >= level if kind == 'above' else price <= level
                elif kind == 'pct_move':
                    ref = number(rule['reference'], positive=True)
                    move = (price / ref - 1) * 100
                    threshold = number(rule['pct'], positive=True)
                    direction = rule.get('direction', 'either')
                    if direction not in ('up', 'down', 'either'):
                        raise ValueError('Invalid percent-alert direction.')
                    hit = move >= threshold if direction == 'up' else (-move >= threshold if direction == 'down' else abs(move) >= threshold)
                else:
                    raise ValueError('Unknown alert type.')
            if hit and not old.get('fired'):
                fired.append({'id': identity, 'type': kind, 'symbol': rule['symbol'], 'at': now.isoformat()})
                updated[key] = {'fired': True, 'at': now.isoformat()}
            elif not hit and rule.get('rearm') and kind in ('above', 'below'):
                updated[key] = {'fired': False}
        except (ValueError, KeyError) as exc:
            errors.append({'id': identity, 'error': str(exc)})
    return {'alerts': fired, 'errors': errors, 'state': updated, 'as_of': now.isoformat(), 'execution_enabled': False}
