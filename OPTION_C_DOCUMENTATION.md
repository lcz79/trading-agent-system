# Option C Implementation: Position Manager Audit & Strict Entry Type Handling

## Overview

This implementation adds comprehensive auditing capabilities and strict entry type validation to the position manager service to prevent unintended MARKET orders and enable full auditability of closed trades.

## Features

### 1. Strict Entry Type Mode

**Environment Variable:** `STRICT_ENTRY_TYPE`

When set to `"1"`, the position manager will reject any order request that does not explicitly specify an `entry_type`.

**Usage:**
```bash
# Enable strict mode
export STRICT_ENTRY_TYPE=1

# Disable strict mode (default)
export STRICT_ENTRY_TYPE=0
```

**Behavior:**
- **Strict Mode OFF (default):** Orders without `entry_type` default to `MARKET` (backward compatible)
- **Strict Mode ON:** Orders without `entry_type` are rejected and the intent is marked as `FAILED`

**Example Request (with strict mode enabled):**
```json
POST /open_position
{
  "symbol": "BTCUSDT",
  "side": "long",
  "leverage": 5.0,
  "size_pct": 0.15,
  "entry_type": "LIMIT",    // Required when STRICT_ENTRY_TYPE=1
  "entry_price": 50000.0    // Required for LIMIT orders
}
```

**Error Response (strict mode, missing entry_type):**
```json
{
  "status": "error",
  "msg": "STRICT_ENTRY_TYPE enabled: entry_type is required (MARKET or LIMIT)",
  "intent_id": "abc123...",
  "symbol": "BTCUSDT",
  "side": "long"
}
```

### 2. Position Metadata with Entry Type Tracking

All positions now track their `entry_type` (MARKET or LIMIT) in the position metadata:

**PositionMetadata fields:**
- `symbol`: Trading pair
- `side`: Position side (long/short)
- `entry_price`: Entry price
- `size`: Position size
- `leverage`: Leverage used
- **`entry_type`**: How the position was entered (MARKET or LIMIT) ← NEW
- `opened_at`: Timestamp when position opened
- `intent_id`: Original intent ID
- Other fields: `tp_pct`, `sl_pct`, `time_in_trade_limit_sec`, `cooldown_sec`, `features`

### 3. Closed Trades Audit Trail

The system now maintains a local audit trail of closed trades in `trading_state.json`:

**Storage:** `closed_trades` array in trading state (bounded to last 500 trades)

**Closed Trade Record Structure:**
```json
{
  "symbol": "BTCUSDT",
  "side": "long",
  "entry_price": 50000.0,
  "entry_type": "LIMIT",
  "opened_at": "2024-01-19T10:30:00",
  "closed_at": "2024-01-19T11:45:00",
  "exit_reason": "stale_prune",  // manual, stale_prune, time_exit, etc.
  "intent_id": "abc123...",
  "leverage": 5.0,
  "size": 0.1
}
```

**When are trades persisted?**
- When `state_cleanup_loop` prunes stale positions (exit_reason: "stale_prune")
- Future: Can be extended to persist on explicit closes, time-based exits, etc.

### 4. Enriched Get Closed Positions Endpoint

The `/get_closed_positions` endpoint now returns enriched data by merging Bybit closed PnL with local audit trail:

**Endpoint:** `GET /get_closed_positions`

**Response Structure (backward compatible):**
```json
[
  {
    // Original Bybit fields (always present)
    "datetime": "2024-01-19 11:45",
    "symbol": "BTCUSDT",
    "side": "sell",           // Bybit closing order side
    "price": 51000.0,         // Exit price
    "closedPnl": 150.0,
    
    // Additional fields (present when matched with local audit trail)
    "pos_side": "long",       // Normalized position side
    "intent_id": "abc123...",
    "entry_type": "LIMIT",
    "entry_price": 50000.0,
    "opened_at": "2024-01-19T10:30:00",
    "exit_reason": "stale_prune",
    "closed_at": "2024-01-19T11:45:00"
  }
]
```

**Matching Strategy:**
1. Normalize Bybit `side` to `pos_side` (buy closes short, sell closes long)
2. Match by `symbol` + `pos_side`
3. Find nearest `closed_at` timestamp within 12-hour window
4. Merge additional fields if match found

**Backward Compatibility:**
- Original fields always present (datetime, symbol, side, price, closedPnl)
- Additional fields only present when match found
- Existing dashboard/clients continue to work without changes

## Trading State Schema Changes

### New Fields in trading_state.json

```json
{
  "version": "1.0.0",
  "last_updated": "2024-01-19T12:00:00",
  "intents": { ... },
  "positions": {
    "BTCUSDT_long": {
      // ... existing fields ...
      "entry_type": "LIMIT"  // NEW: tracks MARKET vs LIMIT
    }
  },
  "cooldowns": [ ... ],
  "trailing_stops": { ... },
  "closed_trades": [         // NEW: audit trail (last 500 trades)
    {
      "symbol": "BTCUSDT",
      "side": "long",
      "entry_type": "LIMIT",
      "entry_price": 50000.0,
      "opened_at": "2024-01-19T10:30:00",
      "closed_at": "2024-01-19T11:45:00",
      "exit_reason": "stale_prune",
      "intent_id": "abc123...",
      "leverage": 5.0,
      "size": 0.1
    }
  ]
}
```

### Backward Compatibility

- Old state files without `closed_trades` are automatically normalized
- Old positions without `entry_type` continue to work (value is `null`)
- No breaking changes to existing functionality

## API Methods Added to TradingState

### add_closed_trade(record: dict, keep_last: int = 500)
Adds a closed trade record to the audit trail. Automatically bounds the array to `keep_last` records.

**Usage:**
```python
from shared.trading_state import get_trading_state

trading_state = get_trading_state()
trading_state.add_closed_trade({
    "symbol": "BTCUSDT",
    "side": "long",
    "entry_type": "MARKET",
    "entry_price": 50000.0,
    "opened_at": datetime.now().isoformat(),
    "closed_at": datetime.now().isoformat(),
    "exit_reason": "manual",
    "intent_id": "abc123",
    "leverage": 5.0,
    "size": 0.1
})
```

### get_closed_trades() -> List[dict]
Retrieves all closed trade records from the audit trail.

**Usage:**
```python
from shared.trading_state import get_trading_state

trading_state = get_trading_state()
closed_trades = trading_state.get_closed_trades()
```

### prune_positions(active_keys: set) -> dict
Updated to return dict with removed keys and position metadata.

**Return Value:**
```python
{
    "removed_keys": ["ETHUSDT_short", "SOLUSDT_long"],
    "removed_positions": [
        {
            "symbol": "ETHUSDT",
            "side": "short",
            "entry_type": "LIMIT",
            # ... other position fields ...
        }
    ]
}
```

## Testing

Run the comprehensive test suite:

```bash
python test_option_c_implementation.py
```

**Tests included:**
1. PositionMetadata entry_type field serialization
2. TradingState closed_trades management
3. prune_positions returns dict with metadata
4. Backward compatibility with old state files
5. Strict entry type validation
6. Closed trade record structure

## Migration Guide

### For Orchestrator Services

**Before (implicit MARKET):**
```python
response = requests.post(
    "http://position_manager:8000/open_position",
    json={
        "symbol": "BTCUSDT",
        "side": "long",
        "leverage": 5.0,
        "size_pct": 0.15
        # entry_type omitted - defaults to MARKET
    }
)
```

**After (explicit LIMIT or MARKET):**
```python
response = requests.post(
    "http://position_manager:8000/open_position",
    json={
        "symbol": "BTCUSDT",
        "side": "long",
        "leverage": 5.0,
        "size_pct": 0.15,
        "entry_type": "LIMIT",  # Explicitly specify
        "entry_price": 50000.0  # Required for LIMIT
    }
)
```

### Enabling Strict Mode

Add to your docker-compose.yml or environment:

```yaml
services:
  position_manager:
    environment:
      - STRICT_ENTRY_TYPE=1  # Enable strict mode
```

### For Dashboard/Frontend

The `/get_closed_positions` endpoint is backward compatible. To use new fields:

```javascript
const closedPositions = await fetch('/get_closed_positions').then(r => r.json());

closedPositions.forEach(trade => {
    // Original fields (always present)
    console.log(`${trade.datetime} ${trade.symbol} ${trade.side}`);
    console.log(`PnL: ${trade.closedPnl}`);
    
    // New fields (present when matched with audit trail)
    if (trade.entry_type) {
        console.log(`Entry Type: ${trade.entry_type}`);
        console.log(`Entry Price: ${trade.entry_price}`);
        console.log(`Exit Reason: ${trade.exit_reason}`);
    }
});
```

## Rollout Recommendations

1. **Phase 1:** Deploy without strict mode (`STRICT_ENTRY_TYPE=0`)
   - Monitor that `entry_type` is being tracked correctly
   - Verify closed_trades audit trail is working
   - Check enriched `/get_closed_positions` returns expected data

2. **Phase 2:** Enable strict mode (`STRICT_ENTRY_TYPE=1`)
   - Update orchestrator to always specify `entry_type`
   - Monitor for rejected orders and fix any missing `entry_type` calls
   - Validate that unintended MARKET orders are prevented

3. **Phase 3:** Use audit trail for analytics
   - Query closed_trades for entry type analysis
   - Measure LIMIT vs MARKET fill rates
   - Analyze exit reasons and improve strategies

## Benefits

1. **Audit Trail:** Full history of closed trades with entry details
2. **Strict Validation:** Prevents accidental MARKET orders
3. **Enhanced Reporting:** Richer data in closed positions endpoint
4. **Backward Compatible:** Existing systems continue to work
5. **Bounded Growth:** Audit trail limited to 500 most recent trades
6. **Deterministic Matching:** Reliable correlation between Bybit and local data

## Limitations

- Closed trades only persisted for positions pruned by `state_cleanup_loop`
  - Future enhancement: persist on all position closes
- Matching strategy uses 12-hour window
  - May not match trades outside this window (rare edge case)
- Audit trail bounded to 500 trades
  - Older trades are rotated out (increase `keep_last` if needed)

## Support

For issues or questions, refer to:
- Test suite: `test_option_c_implementation.py`
- Implementation: `agents/07_position_manager/main.py`
- State schema: `agents/07_position_manager/shared/trading_state.py`
