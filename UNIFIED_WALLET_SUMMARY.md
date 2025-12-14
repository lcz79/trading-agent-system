# Bybit UNIFIED Wallet Detection - Implementation Summary

## Problem Statement

When using Bybit UNIFIED accounts, CCXT returns `USDT.free=None`, causing the trading system to incorrectly report zero available margin even though funds are available for trading. This prevents the system from opening new positions despite having sufficient margin.

## Root Cause

- **UNIFIED accounts** have a different balance structure than standard accounts
- `USDT.free` and `USDT.used` can be `None` while `USDT.total` is non-zero
- The original implementation only checked `USDT.free`, leading to incorrect zero availability

## Solution Overview

Parse raw Bybit API response to extract coin-level Initial Margin (IM) data and calculate available margin using the formula:

```
available_for_new_trades = walletBalance - totalPositionIM - totalOrderIM - locked - buffer
```

Where:
- `walletBalance`: Total USDT balance in account
- `totalPositionIM`: Initial Margin used by open positions
- `totalOrderIM`: Initial Margin reserved for pending orders
- `locked`: Locked funds (e.g., pending withdrawals)
- `buffer`: Safety buffer (10.0 USDT) to prevent margin calls

## Implementation Details

### 1. Position Manager (`agents/07_position_manager/main.py`)

#### New Function: `extract_usdt_coin_data_from_bybit()`
```python
def extract_usdt_coin_data_from_bybit(balance_response: dict) -> Optional[dict]:
    """
    Extracts coin-level USDT data from raw Bybit API response.
    
    Path: balance_response['info']['result']['list'][0]['coin'][USDT]
    
    Returns: {
        'walletBalance': float,
        'equity': float,
        'totalPositionIM': float,
        'totalOrderIM': float,
        'locked': float,
        'availableToWithdraw': float
    }
    """
```

#### Updated Endpoint: `/get_wallet_balance`

**Response Format:**
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

**Detection Logic:**
1. If `USDT.free > 0`: Use normal flow (source: `ccxt_free`)
2. If `USDT.free == None/0` and `USDT.total > 0`: Parse raw Bybit data (source: `bybit_unified_im_derived`)
3. Otherwise: Return zero availability (source: `insufficient_data`)

### 2. Master AI (`agents/04_master_ai_agent/main.py`)

#### System Prompt Update
Added margin constraint as blocking condition:
```
## QUANDO NON APRIRE (HOLD)
...
- **MARGINE INSUFFICIENTE**: available_for_new_trades < 10.0 USDT (BLOCCANTE)
```

#### Decision Logic Update
```python
# Extract wallet data
wallet_available_for_new_trades = portfolio.get('available_for_new_trades', wallet_available)
can_open_new_positions = wallet_available_for_new_trades >= 10.0

# Add margin warning to prompt if insufficient
if not can_open_new_positions:
    margin_text = """
    ⚠️ MARGINE INSUFFICIENTE - NUOVE APERTURE BLOCCATE
    - Available for new trades: X.XX USDT
    - Soglia minima: 10.0 USDT
    - **AZIONE RICHIESTA**: Ritorna solo HOLD per tutti gli asset
    """

# Hard constraint enforcement (post-processing)
if not can_open_new_positions and action in ["OPEN_LONG", "OPEN_SHORT"]:
    action = "HOLD"
    rationale = f"Blocked: insufficient free margin (available_for_new_trades={X.XX}, threshold=10)"
```

### 3. Orchestrator (`agents/orchestrator/main.py`)

#### Logging Enhancement
```python
if action == "HOLD" and "insufficient" in rationale.lower() and "margin" in rationale.lower():
    print(f"🚫 HOLD on {symbol}: {rationale}")
    print(f"   Wallet: available={available_for_new:.2f} USDT (source: {source})")
```

## Data Flow

```
1. Bybit API
   └─> UNIFIED account returns USDT.free=None

2. Position Manager
   ├─> Detects UNIFIED account (free=None, total>0)
   ├─> Parses raw API response for coin-level data
   ├─> Calculates: available = walletBalance - totalPositionIM - totalOrderIM - locked - buffer
   └─> Returns: {equity, available, available_for_new_trades, available_source, components}

3. Orchestrator
   └─> Passes full wallet data to Master AI

4. Master AI
   ├─> Checks: available_for_new_trades >= 10.0
   ├─> If insufficient: adds warning to prompt
   ├─> AI evaluates market conditions
   ├─> Post-processing: converts OPEN to HOLD if margin insufficient
   └─> Returns: decision with clear rationale

5. Orchestrator
   ├─> Receives decision from Master AI
   ├─> If HOLD due to margin: logs constraint with wallet details
   └─> Executes or skips based on decision
```

## Example Scenarios

### Scenario A: UNIFIED Account with Sufficient Margin

**Input (Bybit):**
```json
{
  "USDT": {"total": 250.5, "free": null},
  "info": {
    "result": {
      "list": [{
        "coin": [{
          "coin": "USDT",
          "walletBalance": "245.3",
          "totalPositionIM": "50.0",
          "totalOrderIM": "10.0",
          "locked": "5.0"
        }]
      }]
    }
  }
}
```

**Calculation:**
```
245.3 - 50.0 - 10.0 - 5.0 - 10.0 = 170.3 USDT
```

**Output (Position Manager):**
```json
{
  "equity": 250.5,
  "available": 0.0,
  "available_for_new_trades": 170.3,
  "available_source": "bybit_unified_im_derived"
}
```

**Result:**
- ✅ Master AI evaluates market conditions normally
- ✅ Can open positions if technical signals support it
- ✅ System operates as expected

### Scenario B: UNIFIED Account with Insufficient Margin

**Calculation:**
```
245.3 - 150.0 - 60.0 - 20.3 - 10.0 = 5.0 USDT (< 10.0 threshold)
```

**Output (Position Manager):**
```json
{
  "equity": 250.5,
  "available": 0.0,
  "available_for_new_trades": 5.0,
  "available_source": "bybit_unified_im_derived"
}
```

**Result:**
- 🚫 Master AI blocks all OPEN_LONG/OPEN_SHORT
- 🚫 Returns HOLD with rationale: "Blocked: insufficient free margin (available_for_new_trades=5.00, threshold=10)"
- 🚫 Orchestrator logs constraint and doesn't execute
- 🚫 System waits for margin to increase

### Scenario C: Normal Account (non-UNIFIED)

**Input:**
```json
{
  "USDT": {"total": 1000.0, "free": 850.0, "used": 150.0}
}
```

**Calculation:**
```
850.0 - 10.0 = 840.0 USDT
```

**Output:**
```json
{
  "equity": 1000.0,
  "available": 850.0,
  "available_for_new_trades": 840.0,
  "available_source": "ccxt_free"
}
```

**Result:**
- ✅ Works exactly as before
- ✅ Backward compatibility maintained
- ✅ Additional margin check adds safety

## Testing

### Automated Tests

**Unit Tests (`test_unified_wallet.py`):**
1. ✅ Parsing UNIFIED response
2. ✅ Available calculation
3. ✅ Margin threshold
4. ✅ Response format
5. ✅ Normal account handling

**Integration Test (`test_integration_flow.py`):**
- Demonstrates complete flow for sufficient and insufficient margin scenarios

### Manual Testing

**Check Endpoint:**
```bash
curl http://localhost:8007/get_wallet_balance | jq
```

**Monitor Logs:**
```bash
# Position Manager
docker logs 07_position_manager | grep "UNIFIED wallet"

# Master AI
docker logs 04_master_ai_agent | grep "insufficient margin"

# Orchestrator
docker logs orchestrator | grep "HOLD on"
```

## Configuration

### Environment Variables (Optional)

Currently, the following values are hardcoded but could be made configurable:

```bash
# Buffer to prevent margin calls (default: 10.0 USDT)
WALLET_BUFFER=10.0

# Margin threshold for opening positions (default: 10.0 USDT)
MARGIN_THRESHOLD=10.0
```

## Backward Compatibility

All existing integrations continue to work:

- ✅ `equity` field still present
- ✅ `available` field still present (may be 0 for UNIFIED)
- ✅ New fields are additions, not replacements
- ✅ Normal accounts behave as before
- ✅ Only difference: additional margin check adds safety

## Benefits

1. **Accuracy**: UNIFIED accounts show correct available margin
2. **Safety**: Prevents risky trades with insufficient margin
3. **Transparency**: Clear logging and rationale for all decisions
4. **Reliability**: Comprehensive test coverage
5. **Security**: No vulnerabilities (CodeQL verified)
6. **Compatibility**: Existing integrations unaffected

## Troubleshooting

### Issue: Still showing zero availability

**Check:**
1. Is account type UNIFIED? (Bybit API should return accountType="UNIFIED")
2. Are coin-level fields present in raw response?
3. Is USDT in the coins list?

**Debug:**
```bash
docker exec -it 07_position_manager python3 -c "
import ccxt, os, json
exchange = ccxt.bybit({'apiKey': os.getenv('BYBIT_API_KEY'), 'secret': os.getenv('BYBIT_API_SECRET')})
bal = exchange.fetch_balance(params={'type': 'swap'})
print(json.dumps(bal.get('info', {}), indent=2))
"
```

### Issue: Master AI ignoring margin constraint

**Check:**
1. Is wallet data being passed to Master AI?
2. Is hard constraint enforcement code active?
3. Are there any exceptions in logs?

**Debug:**
```bash
docker logs 04_master_ai_agent 2>&1 | tail -100
```

## Files Modified

1. `agents/07_position_manager/main.py` - Added UNIFIED wallet parsing and detection
2. `agents/04_master_ai_agent/main.py` - Added margin constraint enforcement
3. `agents/orchestrator/main.py` - Added margin constraint logging

## Files Created

1. `test_unified_wallet.py` - Automated unit tests
2. `test_integration_flow.py` - Integration flow demonstration
3. `UNIFIED_WALLET_TESTING.md` - Testing guide
4. `UNIFIED_WALLET_SUMMARY.md` - This summary document

## References

- [Bybit UNIFIED Account Documentation](https://bybit-exchange.github.io/docs/v5/account/wallet-balance)
- Problem Statement: Original issue description
- Test Results: All 5 automated tests passing

## Support

For questions or issues:
1. Check logs for error messages
2. Review `UNIFIED_WALLET_TESTING.md` for troubleshooting
3. Run automated tests to verify functionality
4. Check raw Bybit API response structure

---

**Implementation Date**: December 2024
**Status**: ✅ Complete - All tests passing, no vulnerabilities
**Branch**: `copilot/fix-available-margin-detection`
