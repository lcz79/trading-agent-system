# LIMIT Entry Order Support

## Overview

This document describes the comprehensive end-to-end implementation of LIMIT entry order support in the trading system. The implementation provides DeepSeek AI-driven LIMIT entry decisions, deterministic cancel+replace logic, robust tracking, and lifecycle management while maintaining backward compatibility with MARKET orders.

## Features

### 1. AI-Driven LIMIT Entry Decisions
- DeepSeek AI can now choose between MARKET and LIMIT entry types
- AI specifies exact entry_price for LIMIT orders
- Configurable TTL (time-to-live) via entry_expires_sec (10-3600 seconds)
- Automatic fallback to MARKET if LIMIT parameters are invalid
- Intelligent decision-making based on setup quality and market conditions

### 2. LIMIT Order Submission
- Submit LIMIT orders with a specific entry price
- Automatic TTL (time-to-live) expiry with configurable timeout
- Deterministic tracking using `orderLinkId=intent_id`
- Returns both `orderId` and `orderLinkId` for reliable order management

### 3. Cancel+Replace Logic
- Detects existing pending LIMIT orders for same symbol+direction
- Automatically cancels old order when AI updates entry_price
- Places new LIMIT order with updated parameters
- Idempotent and deterministic state management
- Price change threshold: 0.1% to avoid unnecessary cancellations
- Background monitoring of pending LIMIT orders (30-second loop)
- Automatic detection of order fills
- Post-fill stop-loss placement using MarkPrice trigger
- TTL-based order cancellation
- Robust filtering of non-entry orders (StopLoss/TP/conditional orders)

### 3. Idempotency
- Intent-based order tracking prevents duplicate submissions
- Persistent state across restarts via `trading_state.json`
- Deterministic `orderLinkId` for reliable order identification

### 4. Backward Compatibility
- Default behavior remains MARKET entry orders
- No breaking changes to existing API
- Optional `entry_type` parameter for LIMIT support

## API Usage

### MARKET Order (Default)

```bash
curl -X POST http://position_manager:8000/open_position \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTCUSDT",
    "side": "long",
    "leverage": 5.0,
    "size_pct": 0.15,
    "sl_pct": 0.02
  }'
```

Response:
```json
{
  "status": "executed",
  "id": "bybit-order-id",
  "exchange_order_id": "bybit-order-id",
  "intent_id": "uuid-generated",
  "symbol": "BTCUSDT",
  "side": "long"
}
```

### LIMIT Order

```bash
curl -X POST http://position_manager:8000/open_position \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTCUSDT",
    "side": "long",
    "leverage": 5.0,
    "size_pct": 0.15,
    "sl_pct": 0.02,
    "entry_type": "LIMIT",
    "entry_price": 50000.0,
    "entry_ttl_sec": 3600
  }'
```

Response:
```json
{
  "status": "pending",
  "msg": "LIMIT order submitted, awaiting fill",
  "id": "bybit-order-id",
  "exchange_order_id": "bybit-order-id",
  "exchange_order_link_id": "uuid-generated",
  "intent_id": "uuid-generated",
  "symbol": "BTCUSDT",
  "side": "long",
  "entry_type": "LIMIT",
  "entry_price": 50000.0,
  "expires_at": "2026-01-18T20:00:00.000000"
}
```

## AI Decision Flow

### DeepSeek AI Decision Fields

When making a trading decision, DeepSeek AI now returns:

```json
{
  "symbol": "BTCUSDT",
  "action": "OPEN_LONG",
  "leverage": 5.0,
  "size_pct": 0.15,
  "confidence": 80,
  "rationale": "Setup LONG with price near support. Using LIMIT entry for precision.",
  "tp_pct": 0.02,
  "sl_pct": 0.015,
  "time_in_trade_limit_sec": 3600,
  "entry_type": "LIMIT",
  "entry_price": 50000.0,
  "entry_expires_sec": 240
}
```

### AI Decision Semantics

**entry_type**: "MARKET" | "LIMIT"
- "MARKET": Immediate entry at market price (default)
- "LIMIT": Entry at specific price, waits for fill or TTL expiry

**entry_price** (required when entry_type="LIMIT"): Exact entry price
- For LONG: typically slightly below current price (e.g., -0.1% to -0.5%)
- For SHORT: typically slightly above current price (e.g., +0.1% to +0.5%)
- If invalid or missing, system falls back to MARKET with warning

**entry_expires_sec** (optional, default 240): TTL in seconds (range 10-3600)
- Strong setup: 60-120 sec (1-2 min)
- Normal setup: 180-300 sec (3-5 min)
- Patient setup: 300-600 sec (5-10 min)
- Max recommended: 600 sec (10 min) for scalping

### When AI Chooses LIMIT Entry

✅ **Use LIMIT when:**
- Price near support/resistance, want precise entry
- Clean setup but price not ideal yet
- Want to optimize entry and reduce slippage
- High confidence price will reach target level

❌ **Use MARKET when:**
- Time-sensitive breakout/momentum trade
- High volatility (LIMIT might not fill)
- Lower confidence setup (want quick entry)
- Need immediate position establishment

### Validation and Fallback

The system validates LIMIT parameters and falls back to MARKET if:
- `entry_type=LIMIT` but `entry_price` is missing or invalid (≤ 0)
- System logs warning: `"⚠️ LIMIT entry without valid entry_price: falling back to MARKET"`
- Rationale updated: `"[FALLBACK TO MARKET: invalid entry_price] <original rationale>"`
- `entry_expires_sec` clamped to range [10, 3600] if out of bounds

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `symbol` | string | Yes | - | Trading symbol (e.g., "BTCUSDT") |
| `side` | string | Yes | - | Position side: "long"/"buy" or "short"/"sell" |
| `leverage` | float | Yes | - | Leverage multiplier (e.g., 5.0) |
| `size_pct` | float | Yes | - | Position size as % of available balance (e.g., 0.15 = 15%) |
| `sl_pct` | float | Yes | - | Stop-loss percentage (e.g., 0.02 = 2%) |
| `entry_type` | string | No | "MARKET" | Order type: "MARKET" or "LIMIT" |
| `entry_price` | float | Required for LIMIT | null | Entry price for LIMIT orders |
| `entry_ttl_sec` | int | No | 3600 | Time-to-live in seconds for LIMIT orders |
| `intent_id` | string | No | auto-generated | Custom intent ID for idempotency |
| `tp_pct` | float | No | null | Take-profit percentage (policy: disabled) |
| `time_in_trade_limit_sec` | int | No | null | Max holding time for scalping |
| `cooldown_sec` | int | No | 300 | Cooldown after position close |
| `features` | dict | No | {} | Market features snapshot |

## Data Model

### OrderIntent

```python
@dataclass
class OrderIntent:
    intent_id: str
    symbol: str
    side: str
    leverage: float
    size_pct: float
    entry_type: str = "MARKET"  # "MARKET" or "LIMIT"
    entry_price: Optional[float] = None
    entry_expires_at: Optional[str] = None  # ISO timestamp
    exchange_order_id: Optional[str] = None  # Bybit orderId
    exchange_order_link_id: Optional[str] = None  # Client orderLinkId
    status: OrderStatus = OrderStatus.PENDING
    # ... other fields
```

### OrderStatus Lifecycle

```
MARKET Order:
PENDING → EXECUTING → EXECUTED

LIMIT Order:
PENDING → (awaiting fill) → EXECUTED
PENDING → (TTL expired) → CANCELLED
PENDING → (rejected) → CANCELLED
```

## Implementation Details

### 1. Order Creation

**MARKET Order:**
```python
res = exchange.create_order(
    symbol, "market", side, qty,
    params={"category": "linear", "positionIdx": pos_idx}
)
```

**LIMIT Order:**
```python
res = exchange.create_order(
    symbol, "limit", side, qty, price,
    params={
        "category": "linear",
        "positionIdx": pos_idx,
        "orderLinkId": intent_id  # For deterministic tracking
    }
)
```

### 2. Pending Order Tracking

The `check_pending_entry_orders()` function runs in a background loop (30s interval) and:

1. **Queries Bybit v5** for each pending LIMIT intent:
   - First tries by `orderLinkId` (most reliable)
   - Falls back to `orderId` if available

2. **Filters non-entry orders**:
   ```python
   if order_data.get("stopOrderType"):
       continue  # Skip SL/TP orders
   if "StopLoss" in order_data.get("createType", ""):
       continue  # Skip conditional orders
   if order_data.get("reduceOnly"):
       continue  # Skip reduce-only orders
   ```

3. **Handles order states**:
   - **Cancelled/Rejected/Deactivated**: Mark intent CANCELLED
   - **Expired (TTL)**: Cancel order, mark intent CANCELLED
   - **Filled**: Set SL via `trading_stop`, mark intent EXECUTED
   - **New/PartiallyFilled**: Keep pending

### 3. Post-Fill SL Placement

When a LIMIT order fills, the system:

1. Detects fill via order status query
2. Calculates SL price based on `sl_pct` or ATR
3. Sets SL server-side using MarkPrice trigger:
   ```python
   exchange.private_post_v5_position_trading_stop({
       "category": "linear",
       "symbol": symbol_id,
       "tpslMode": "Full",
       "stopLoss": sl_price,
       "slTriggerBy": "MarkPrice",
       "positionIdx": pos_idx
   })
   ```
4. Retries with exponential backoff (5 attempts)
5. Emergency closes position if SL fails to set

### 4. Cancel+Replace Logic

**Orchestrator automatically manages LIMIT order updates:**

When a new AI decision arrives with `entry_type=LIMIT`:

1. **Query pending intents** from position manager
2. **Check for existing PENDING LIMIT** for same symbol+direction
3. **Compare entry_price**:
   - If price changed > 0.1%: Cancel old order, submit new
   - If price changed ≤ 0.1%: Skip duplicate submission
4. **Cancel old order** via `orderLinkId` (preferred) or `orderId`
5. **Submit new order** with updated parameters

**Example Flow:**

```
Cycle 1: AI decides LIMIT LONG BTCUSDT at 50000
→ Submit LIMIT order at 50000

Cycle 2: AI decides LIMIT LONG BTCUSDT at 50500 (price moved)
→ Detect existing pending order at 50000
→ Price diff: 1.0% > 0.1% threshold
→ Cancel order at 50000
→ Submit new LIMIT order at 50500

Cycle 3: AI decides LIMIT LONG BTCUSDT at 50510 (small change)
→ Detect existing pending order at 50500
→ Price diff: 0.02% < 0.1% threshold
→ Skip - order already pending at similar price
```

**Benefits:**
- Automatic price adjustment as market moves
- Avoids duplicate orders
- Maintains single pending entry per symbol+direction (unless scale-in enabled)
- Deterministic state management

**Endpoints Added:**

```bash
# Query pending intents
GET /get_pending_intents
Response: {
  "intents": [
    {
      "intent_id": "abc123",
      "symbol": "BTCUSDT",
      "side": "long",
      "entry_type": "LIMIT",
      "entry_price": 50000.0,
      "status": "PENDING",
      ...
    }
  ],
  "count": 1
}

# Cancel an intent
POST /cancel_intent
Body: {"intent_id": "abc123"}
Response: {
  "status": "success",
  "msg": "Intent abc123 cancelled",
  "intent_id": "abc123"
}
```

When a LIMIT order expires:

1. Checks `entry_expires_at` against current time
2. Cancels order via Bybit API:
   ```python
   exchange.private_post_v5_order_cancel({
       "category": "linear",
       "symbol": symbol_id,
       "orderLinkId": intent_id  # Prefer orderLinkId
   })
   ```
3. Marks intent as CANCELLED with reason "LIMIT entry expired (TTL)"

## Monitoring and Logging

### Entry Order Events

```
📋 LIMIT ENTRY: BTCUSDT side=buy qty=0.5 price=50000.0 orderLinkId=abc12345
✅ LIMIT order submitted: BTCUSDT long orderId=12345678 orderLinkId=abc12345
   ⏰ Will expire at: 2026-01-18T20:00:00.000000
```

### Pending Order Checks

```
📋 Checking 3 pending LIMIT entry orders
   🔍 Found order by orderLinkId: abc12345
   📊 ENTRY ORDER abc12345: status=New
   ⏳ Order still pending: New
```

### Order Fills

```
   ✅ ENTRY ORDER FILLED: abc12345
   ✅ Post-fill SL set: BTCUSDT SL=49000.0 trigger=MarkPrice
   ✅ Position metadata stored for BTCUSDT long
```

### TTL Expiry

```
   ⏰ LIMIT entry expired, cancelling: abc12345
   ✅ Order cancelled successfully: abc12345
```

### Non-Entry Order Filtering

```
   ⏭️ Skipping non-entry order (stopOrderType=StopLoss)
   ⏭️ Skipping SL/TP order (createType=CreateByStopLoss)
   ⏭️ Skipping reduceOnly order
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_ENTRY_TTL_SEC` | 3600 | Default TTL for LIMIT orders (1 hour) |
| `ENTRY_SL_USE_ATR` | true | Use ATR for entry SL calculation |
| `ENTRY_SL_MAX_PCT` | 0.02 | Maximum SL percentage (2%) |
| `ENTRY_SL_MIN_PCT_DEFAULT` | 0.007 | Minimum SL percentage (0.7%) |
| `BYBIT_HEDGE_MODE` | false | Allow long+short positions on same symbol simultaneously |
| `ALLOW_SCALE_IN` | false | Allow multiple entries in same direction (use with caution) |
| `MAX_PENDING_ENTRIES_PER_SYMBOL_SIDE` | 1 | Max pending LIMIT entries per symbol+side (if ALLOW_SCALE_IN=true) |

### Scale-In Guardrail Behavior

**Default Mode (ALLOW_SCALE_IN=false):**
- System blocks new entries if position already open on same symbol (one-way mode)
- Prevents accidental position doubling or flip/churn
- Safest mode for most strategies

**Scale-In Mode (ALLOW_SCALE_IN=true):**
- Allows multiple LIMIT entries in same direction on same symbol
- Useful for DCA (dollar-cost averaging) or scaling into positions
- **Safety checks:**
  - Max pending entries per symbol+side enforced (default 1)
  - Each entry tracked separately with unique intent_id
  - System prevents exceeding `MAX_PENDING_ENTRIES_PER_SYMBOL_SIDE`
- **Logs:**
  ```
  ✅ Scale-in allowed: 1/2 pending entries for BTCUSDT long
  🧯 SKIP OPEN_LONG on BTCUSDT: max pending entries (2/2) reached for scale-in
  ```

**Example Configuration:**
```bash
# .env
ALLOW_SCALE_IN=true
MAX_PENDING_ENTRIES_PER_SYMBOL_SIDE=2

# Result: System allows up to 2 pending LIMIT orders per symbol+side
# e.g., BTCUSDT LONG at 50000 + BTCUSDT LONG at 49500
```

**Recommendation:**
- Start with `ALLOW_SCALE_IN=false` (default)
- Only enable scale-in if your strategy explicitly requires it
- Keep `MAX_PENDING_ENTRIES_PER_SYMBOL_SIDE` low (1-2) to avoid over-exposure

## Error Handling

### Critical Failures

**SL Placement Failure:**
```python
if not _sl_ok:
    print(f"❌ CRITICAL: Post-fill SL NOT set for {symbol}")
    execute_close_position(symbol, exit_reason="emergency")
```

**Invalid LIMIT Parameters:**
```python
if entry_type == "LIMIT" and (not entry_price or entry_price <= 0):
    return {"status": "error", "msg": "LIMIT order requires valid entry_price"}
```

### Graceful Degradation

- Order not found: Check TTL expiry, mark CANCELLED if expired
- API timeout: Retry with exponential backoff
- Persistence errors: Log warning, continue operation

## Testing

### Test Suite

Run the comprehensive test suite:
```bash
python3 test_limit_entry_orders.py
```

**Test Coverage:**
- ✅ OrderIntent data model with LIMIT fields
- ✅ OrderRequest API model validation
- ✅ TradingState update with exchange_order_link_id
- ✅ Order filtering logic (entry vs SL/TP)
- ✅ TTL expiration detection
- ✅ Backward compatibility with MARKET orders

### Manual Testing

**1. Submit LIMIT Order:**
```bash
curl -X POST http://localhost:8000/open_position \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTCUSDT",
    "side": "long",
    "leverage": 3.0,
    "size_pct": 0.10,
    "sl_pct": 0.015,
    "entry_type": "LIMIT",
    "entry_price": 48000.0,
    "entry_ttl_sec": 1800
  }'
```

**2. Check Trading State:**
```bash
cat /data/trading_state.json | jq '.intents'
```

**3. Monitor Logs:**
```bash
docker logs -f position_manager | grep "LIMIT\|ENTRY"
```

## Acceptance Criteria

✅ **All criteria met:**

1. **LIMIT order submission**: Returns both `orderId` and `orderLinkId`
2. **Pending entry tracking**: Correctly locates entry order despite presence of SL orders
3. **TTL cancellation**: Reliably cancels expired orders using `orderLinkId`
4. **Post-fill SL placement**: Sets SL server-side when entry fills, marks intent EXECUTED
5. **Backward compatibility**: No regression for MARKET entries (default behavior)

## Security Considerations

1. **Intent-based idempotency**: Prevents duplicate order submissions
2. **Emergency close on SL failure**: Protects against unprotected positions
3. **Order filtering**: Prevents accidental cancellation of SL/TP orders
4. **Deterministic tracking**: `orderLinkId=intent_id` ensures reliable order identification

## Performance

- **Background loop interval**: 30 seconds
- **Query efficiency**: Direct Bybit v5 API queries by orderLinkId
- **State persistence**: Optimized JSON serialization
- **Memory usage**: O(n) where n = number of pending LIMIT orders

## Future Enhancements

1. **Partial fills**: Handle PartiallyFilled status with cumulative tracking
2. **Dynamic TTL**: Adjust TTL based on market volatility
3. **Order modification**: Support price updates for pending orders
4. **Multiple entry levels**: Ladder orders at different prices
5. **Conditional triggers**: Entry based on technical indicators

## Troubleshooting

### Order Not Found

**Symptom**: "Order not found for intent abc12345"

**Causes**:
- Order already filled/cancelled
- Network delay in Bybit API
- Order ID mismatch

**Solution**: Check Bybit web interface, verify orderLinkId matches intent_id

### SL Not Set After Fill

**Symptom**: "CRITICAL: Post-fill SL NOT set"

**Causes**:
- Position not opened yet (timing issue)
- Bybit API throttling
- Invalid SL price

**Solution**: Check Bybit rate limits, verify position exists, emergency close executed

### TTL Expiry Not Working

**Symptom**: Order not cancelled after TTL

**Causes**:
- Background loop not running
- Clock skew
- Order already filled

**Solution**: Check container logs, verify system time, check order status on Bybit

## References

- Bybit v5 API Documentation: https://bybit-exchange.github.io/docs/v5/intro
- ccxt Documentation: https://docs.ccxt.com/
- Trading State Schema: `agents/07_position_manager/shared/trading_state.py`
- Position Manager: `agents/07_position_manager/main.py`
