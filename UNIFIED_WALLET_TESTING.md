# Testing Guide: Bybit UNIFIED Wallet Detection

This guide explains how to test the Bybit UNIFIED account wallet detection and margin constraint features.

## Overview

This fix addresses the issue where Bybit UNIFIED accounts return `USDT.free=None`, causing the system to incorrectly report zero available margin even when funds are available for trading.

## Changes Made

### 1. Position Manager (`agents/07_position_manager/main.py`)
- Added `extract_usdt_coin_data_from_bybit()` function to parse raw Bybit API response
- Updated `/get_wallet_balance` endpoint to:
  - Detect UNIFIED accounts
  - Calculate `available_for_new_trades` using Initial Margin formula
  - Return extended response with source and components
  - Maintain backward compatibility

### 2. Master AI (`agents/04_master_ai_agent/main.py`)
- Updated system prompt to include margin constraint
- Added hard constraint enforcement to block OPEN_LONG/OPEN_SHORT when `available_for_new_trades < 10.0`
- Added margin warning text in AI context

### 3. Orchestrator (`agents/orchestrator/main.py`)
- Added logging for HOLD decisions due to insufficient margin
- Displays available amount and source

## Running Tests

### Automated Unit Tests

Run the test suite to verify all components work correctly:

```bash
python3 test_unified_wallet.py
```

Expected output:
```
============================================================
BYBIT UNIFIED WALLET DETECTION - TEST SUITE
============================================================
...
Result: 5/5 tests passed
🎉 All tests passed!
```

### Manual Integration Tests

#### Test 1: Check Wallet Balance Endpoint

With the system running, check the wallet balance:

```bash
# If running locally
curl http://localhost:8007/get_wallet_balance

# If running in Docker
curl http://localhost:8007/get_wallet_balance
```

**Expected response for UNIFIED account:**
```json
{
  "equity": 250.5,
  "available": 0.0,
  "available_for_new_trades": 170.3,
  "available_source": "bybit_unified_im_derived",
  "components": {
    "walletBalance": 245.3,
    "totalPositionIM": 50.0,
    "totalOrderIM": 10.0,
    "locked": 5.0,
    "buffer": 10.0,
    "derived_available": 170.3
  }
}
```

**Expected response for normal account:**
```json
{
  "equity": 1000.0,
  "available": 850.0,
  "available_for_new_trades": 840.0,
  "available_source": "ccxt_free",
  "components": {
    "buffer": 10.0,
    "free": 850.0
  }
}
```

#### Test 2: Verify Margin Constraint in Master AI

Check the logs when Master AI makes decisions:

```bash
# Check Position Manager logs for wallet info
docker logs 07_position_manager | grep "UNIFIED wallet"

# Check Master AI logs for margin blocking
docker logs 04_master_ai_agent | grep "insufficient margin"

# Check Orchestrator logs for HOLD due to margin
docker logs orchestrator | grep "HOLD on"
```

**Expected log outputs:**

Position Manager (when using UNIFIED):
```
💰 UNIFIED wallet: equity=250.50, derived_available=170.30
```

Master AI (when blocking due to insufficient margin):
```
🚫 Blocked OPEN_LONG on BTCUSDT: insufficient margin (available=5.50, threshold=10.0)
```

Orchestrator (when Master returns HOLD due to margin):
```
🚫 HOLD on BTCUSDT: Blocked: insufficient free margin (available_for_new_trades=5.50, threshold=10)
   Wallet: available=5.50 USDT (source: bybit_unified_im_derived)
```

#### Test 3: Verify System Behavior with Different Margin Levels

**Scenario A: Sufficient margin (> 10 USDT)**
- System should allow opening new positions
- Master AI should evaluate market conditions normally
- No margin-related warnings in logs

**Scenario B: Insufficient margin (< 10 USDT)**
- System should block opening new positions
- Master AI should return HOLD for all assets
- Clear margin warnings in logs
- Rationale includes "insufficient free margin"

#### Test 4: Check Dashboard Decision History

Navigate to the dashboard (if available) and check the AI decisions history. Look for decisions with:
- Action: HOLD
- Rationale containing "insufficient free margin" or "Blocked"
- Shows available_for_new_trades value

## Validation Checklist

Use this checklist to verify the fix is working correctly:

- [ ] `/get_wallet_balance` returns all required fields (equity, available, available_for_new_trades, available_source, components)
- [ ] UNIFIED accounts show `available_source: "bybit_unified_im_derived"`
- [ ] Normal accounts show `available_source: "ccxt_free"`
- [ ] `available_for_new_trades` is calculated correctly using IM formula for UNIFIED accounts
- [ ] `available_for_new_trades` equals `available - buffer` for normal accounts
- [ ] Master AI blocks OPEN_LONG/OPEN_SHORT when `available_for_new_trades < 10.0`
- [ ] Blocked decisions have clear rationale explaining margin constraint
- [ ] Orchestrator logs show margin information when HOLD occurs due to margin
- [ ] System works normally when margin is sufficient
- [ ] Backward compatibility maintained (equity and available fields still present)

## Troubleshooting

### Issue: Still showing zero availability on UNIFIED account

**Check:**
1. Verify Position Manager logs show "UNIFIED wallet" message
2. Check raw balance response structure matches expected format
3. Verify USDT coin data is present in response

**Debug:**
```bash
# Add debug logging in Position Manager
docker exec -it 07_position_manager python3 -c "
import ccxt, os, json
exchange = ccxt.bybit({
    'apiKey': os.getenv('BYBIT_API_KEY'),
    'secret': os.getenv('BYBIT_API_SECRET')
})
bal = exchange.fetch_balance(params={'type': 'swap'})
print(json.dumps(bal.get('info', {}), indent=2))
"
```

### Issue: Master AI still trying to open positions with low margin

**Check:**
1. Verify Master AI is receiving wallet data with new fields
2. Check hard constraint enforcement is working
3. Verify threshold is set to 10.0

**Debug:**
```bash
# Check Master AI logs for wallet data
docker logs 04_master_ai_agent 2>&1 | grep "wallet"

# Verify constraint enforcement
docker logs 04_master_ai_agent 2>&1 | grep "Blocked"
```

### Issue: Components showing empty or incorrect values

**Check:**
1. Verify Bybit API response structure hasn't changed
2. Check parsing logic in `extract_usdt_coin_data_from_bybit()`
3. Verify USDT is in the coins list

**Solution:**
Update the parsing logic to match current Bybit API format if needed.

## Expected Behavior Summary

### UNIFIED Account with Sufficient Margin
- Position Manager: Parses raw Bybit data, calculates available ~170 USDT
- Master AI: Evaluates market conditions normally
- Orchestrator: Executes OPEN_LONG/OPEN_SHORT if conditions met
- System: Trades normally

### UNIFIED Account with Insufficient Margin
- Position Manager: Parses raw Bybit data, calculates available ~5 USDT
- Master AI: Blocks all OPEN_LONG/OPEN_SHORT, returns HOLD
- Orchestrator: Logs margin constraint, doesn't execute
- System: Waits for margin to increase

### Normal Account
- Position Manager: Uses USDT.free directly
- Master AI: Enforces same 10 USDT threshold
- Orchestrator: Same behavior as UNIFIED
- System: Works as before with additional margin check

## Success Criteria

✅ All automated tests pass (5/5)
✅ UNIFIED accounts show correct available_for_new_trades
✅ Normal accounts work without issues
✅ Margin constraint blocks entries when < 10 USDT
✅ Clear logging and rationale provided
✅ Backward compatibility maintained
✅ User can open manual trades even when system shows constraints (as expected)

## Notes

- The buffer of 10.0 USDT is hardcoded to prevent margin calls
- The threshold for blocking entries is also 10.0 USDT
- These values can be made configurable via environment variables if needed
- The system uses Initial Margin (IM) calculation for UNIFIED accounts, which is more accurate than relying on `USDT.free`
