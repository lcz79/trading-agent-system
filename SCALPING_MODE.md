# Scalping Mode Documentation

## Overview

The trading system now operates in **scalping-first mode** with aggressive but profitable strategies. This mode is designed for high-frequency trading with tight stop losses and quick exits.

## Key Features

### 1. Intent ID Idempotency

Every order request includes a unique `intent_id` that prevents duplicate orders:

- **Automatic deduplication**: Same `intent_id` = no duplicate order
- **Persistent memory**: Intents are stored in `/data/trading_state.json`
- **TTL**: Old intents are cleaned up after 6 hours
- **Recovery**: Idempotency works even after system restarts

**Example:**
```python
{
    "symbol": "BTCUSDT",
    "side": "OPEN_LONG",
    "leverage": 5.0,
    "size_pct": 0.15,
    "intent_id": "unique-uuid-here",  # Prevents duplicates
    "tp_pct": 0.02,
    "sl_pct": 0.015,
    "time_in_trade_limit_sec": 1800
}
```

### 2. Time-Based Exit

Positions are automatically closed when they exceed their `time_in_trade_limit_sec`:

- **Background monitoring**: Checks every 30 seconds
- **Configurable limits**: Default 40 minutes (20-60 min range)
- **Learning integration**: Exit events are recorded for analysis
- **Environment variable**: `DEFAULT_TIME_IN_TRADE_LIMIT_SEC=2400` (40 minutes)

**How it works:**
1. Position opened with `time_in_trade_limit_sec=1800` (30 min)
2. Background job checks every 30s for expired positions
3. If position age > limit, automatic closure is triggered
4. Exit is logged with reason "Time limit exceeded (scalping mode)"

### 3. Scalping Parameters

The Master AI now outputs scalping-specific parameters for every trade:

| Parameter | Description | Example |
|-----------|-------------|---------|
| `tp_pct` | Take profit % (leveraged) | 0.02 (2%) |
| `sl_pct` | Stop loss % (leveraged) | 0.015 (1.5%) |
| `time_in_trade_limit_sec` | Max holding time | 1800 (30 min) |
| `cooldown_sec` | Cooldown after close | 900 (15 min) |
| `trail_activation_roi` | ROI to activate trailing | 0.01 (1%) |

**Guidelines from AI Prompt:**
- **High confidence (>85%)**: TP 2.5-3%, SL 1.5-2%, Time 20-30 min
- **Medium confidence (70-85%)**: TP 1.5-2.5%, SL 1.5-2%, Time 30-40 min
- **Low confidence (50-70%)**: TP 1-1.5%, SL 1-1.5%, Time 40-60 min

### 4. Master AI Scalping Prompt

The AI is now configured for aggressive scalping with strong guardrails:

**Philosophy:**
- High frequency trades on 1m, 5m, 15m timeframes
- Small targets (1-3% ROI) with tight stops (1-2%)
- Quick exits (20-60 minutes max)
- Serious risk management (no revenge trading)

**Guardrails (ALWAYS enforced):**
- `INSUFFICIENT_MARGIN`: < 10 USDT available
- `MAX_POSITIONS`: Position limit reached
- `COOLDOWN`: Recent close in same direction
- `DRAWDOWN_GUARD`: System drawdown < -10%
- `CRASH_GUARD`: Violent movement against direction
  - Block LONG if 5m return <= -0.6%
  - Block SHORT if 5m return >= +0.6%
- `CONFLICTING_SIGNALS`: Mixed indicators (avoid chop)
- `LOW_CONFIDENCE`: AI confidence < 50%

### 5. REVERSE Logic Disabled

REVERSE is disabled by default for scalping mode:

- **Environment**: `POSITION_MANAGER_ENABLE_REVERSE=false` (default)
- **Orchestrator**: Converts REVERSE to CLOSE when disabled
- **Rationale**: REVERSE is too risky for fast scalping trades
- **Allowed actions**: Only OPEN, CLOSE, HOLD

### 6. One-Way Mode

System operates in One-Way mode (single position per symbol):

- **Position index**: Always uses `positionIdx=0`
- **No hedging**: Cannot have both LONG and SHORT on same symbol
- **Validation**: Rejects opposite direction if position exists
- **Environment**: `BYBIT_HEDGE_MODE=false` (default)

## Configuration

### Environment Variables

```bash
# Scalping time limit (seconds)
DEFAULT_TIME_IN_TRADE_LIMIT_SEC=2400  # 40 minutes (20-60 range)

# Cooldown duration (minutes)
COOLDOWN_MINUTES=5  # Quick cooldown for scalping

# Position Manager settings
POSITION_MANAGER_ENABLE_REVERSE=false  # REVERSE disabled for scalping
POSITION_MANAGER_MANUAL_ONLY=true      # Disable auto-close (use trailing)

# Mode settings
BYBIT_HEDGE_MODE=false  # One-Way mode (required for scalping)

# Trading state file
TRADING_STATE_FILE=/data/trading_state.json  # Unified state storage
```

### Trading State Structure

The system uses a unified state file at `/data/trading_state.json`:

```json
{
  "version": "1.0.0",
  "last_updated": "2025-12-27T10:30:00.000Z",
  "order_intents": {
    "uuid-1": {
      "intent_id": "uuid-1",
      "symbol": "BTCUSDT",
      "action": "OPEN_LONG",
      "status": "executed",
      "exchange_order_id": "12345",
      "tp_pct": 0.02,
      "sl_pct": 0.015,
      "time_in_trade_limit_sec": 1800,
      "cooldown_sec": 900
    }
  },
  "cooldowns": [
    {
      "symbol": "ETHUSDT",
      "direction": "long",
      "closed_at": "2025-12-27T10:15:00.000Z",
      "reason": "Position closed",
      "cooldown_sec": 900
    }
  ],
  "position_metadata": {
    "BTCUSDT_long": {
      "symbol": "BTCUSDT",
      "direction": "long",
      "opened_at": "2025-12-27T10:00:00.000Z",
      "intent_id": "uuid-1",
      "time_in_trade_limit_sec": 1800,
      "entry_price": 50000.0,
      "size": 0.01,
      "leverage": 5.0,
      "cooldown_sec": 900
    }
  },
  "trailing_stops": {
    "BTCUSDT_long": {
      "symbol": "BTCUSDT",
      "direction": "long",
      "highest_roi": 0.025,
      "current_sl_price": 50500.0,
      "last_updated": "2025-12-27T10:20:00.000Z",
      "is_active": true
    }
  }
}
```

## Testing

Run the scalping features test suite:

```bash
python3 test_scalping_features.py
```

This tests:
1. Intent ID idempotency
2. Cooldown management
3. Position metadata & time-based exits
4. Scalping decision model validation

## Troubleshooting

### Issue: Duplicate orders being placed

**Cause**: `intent_id` not being passed or not unique  
**Solution**: Orchestrator generates UUID for each decision. Verify logs for `intent_id`.

### Issue: Positions not closing after time limit

**Cause**: Position monitor loop not running or `time_in_trade_limit_sec` not set  
**Solution**: 
- Check logs for "Position monitor loop started"
- Verify AI decisions include `time_in_trade_limit_sec` parameter
- Check `/data/trading_state.json` for position metadata

### Issue: REVERSE action being executed

**Cause**: `POSITION_MANAGER_ENABLE_REVERSE` set to true  
**Solution**: Set `POSITION_MANAGER_ENABLE_REVERSE=false` (default)

### Issue: Opposite direction order accepted in One-Way mode

**Cause**: Existing position check not working  
**Solution**: 
- Verify `BYBIT_HEDGE_MODE=false`
- Check Position Manager logs for "ONE-WAY MODE" rejection
- Ensure positions are being tracked correctly

### Issue: Cooldown not preventing reopening

**Cause**: Cooldown not being saved to trading_state  
**Solution**:
- Check logs for "Cooldown saved for {symbol} {direction}"
- Verify `/data/trading_state.json` has cooldown entries
- Check cooldown expiration time is correct

## Migration Notes

### From Previous Version

1. **Cooldown files**: Old `/data/closed_cooldown.json` is deprecated but still used as fallback
2. **Intent tracking**: New `/data/trading_state.json` manages all state
3. **AI decisions**: Now include scalping parameters (backward compatible)
4. **REVERSE**: Disabled by default (no behavior change for new deployments)

### Cleanup

The system automatically cleans up:
- Old intents (> 6 hours): Every hour
- Expired cooldowns: Every hour
- No manual intervention needed

## Performance Expectations

### Scalping Mode Targets

- **Win Rate**: 55-65% (more frequent, smaller wins)
- **Average Trade Duration**: 20-40 minutes
- **Daily Trades**: 10-30 (depending on volatility)
- **Average ROI per Trade**: 1-3% (leveraged)
- **Max Drawdown**: < 10% (system-wide guard)

### Risk Management

- **Leverage**: 3-10x (dynamically adjusted)
- **Position Size**: 8-20% of capital per trade
- **Stop Loss**: 1-2% (tight for quick exit)
- **Time Limit**: 20-60 minutes (prevent holding losers)
- **Cooldown**: 5-30 minutes (prevent revenge trading)

## Further Reading

- **SCALPING_REFACTOR_STATUS.md**: Detailed implementation status
- **IMPLEMENTATION_SUMMARY_REFACTOR.md**: Technical architecture
- **PR_README.md**: Original PR documentation
- **CRASH_GUARD_DOCUMENTATION.md**: Crash guard implementation
