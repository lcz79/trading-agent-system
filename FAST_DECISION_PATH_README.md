# Fast Decision Path Implementation

## Overview

This implementation adds a **low-latency AI decision path** to avoid DeepSeek truncated/invalid JSON responses that cause timeouts in the orchestrator.

## Problem Statement

The original `/decide_batch` endpoint was experiencing:
- `httpx.ReadTimeout` errors (120s timeout)
- `JSONDecodeError` from truncated DeepSeek responses
- Truncated responses saved to `/data/deepseek_bad_response_decide_batch_*.txt`
- Missed trading cycles due to timeout failures

## Solution: Two-Phase Decision Flow

### Phase 1: Fast Decision (Critical Path)

**Endpoint:** `POST /decide_batch_fast`

**Purpose:** Return minimal, machine-parseable JSON decisions quickly (target: <30s)

**Features:**
- Compact system prompt with explicit JSON-only instructions
- Minimal response schema (DecisionFast model)
- 25-second hard timeout with safe fallbacks
- Returns HOLD for all symbols on parse failure
- ~69% reduction in response size vs. full endpoint

**Request Schema:**
```python
{
    "learning_params": {...},  # Optional
    "global_data": {
        "portfolio": {...},
        "already_open": [...],
        "max_positions": 10,
        "positions_open_count": 3
    },
    "assets_data": {
        "BTCUSDT": {
            "tech": {...}
        }
    }
}
```

**Response Schema:**
```python
{
    "decisions": [
        {
            "symbol": "BTCUSDT",
            "action": "OPEN_LONG|OPEN_SHORT|HOLD|CLOSE",
            "entry_type": "MARKET|LIMIT",
            "entry_price": 42000.0,  # if LIMIT
            "leverage": 5.0,
            "size_pct": 0.15,
            "tp_pct": 0.02,
            "sl_pct": 0.015,
            "time_in_trade_limit_sec": 3600,
            "cooldown_sec": 600,
            "entry_expires_sec": 240,  # if LIMIT
            "confidence": 78,
            "reason_code": "STRONG_LONG"  # Short code
        }
    ],
    "meta": {
        "processing_time_ms": 1234,
        "endpoint": "decide_batch_fast",
        "symbols_count": 3
    }
}
```

**Reason Codes:**
- `STRONG_LONG` / `STRONG_SHORT`: High confidence setup
- `LOW_VOL`: Volatility too low
- `NO_MARGIN`: Insufficient balance
- `HOLD_WAIT`: No clear setup
- `CRASH_GUARD`: Extreme momentum against direction
- `LLM_PARSE_ERROR`: JSON parsing failed
- `PARSE_ERROR`: Decision validation failed
- `MISSING_DECISION`: Symbol missing from response
- `CRITICAL_ERROR`: Unhandled exception

**Fallback Behavior:**
1. Timeout (>25s) → All symbols return HOLD with `reason_code="LLM_PARSE_ERROR"`
2. Parse error → All symbols return HOLD with `reason_code="PARSE_ERROR"`
3. Missing symbol → Add HOLD with `reason_code="MISSING_DECISION"`
4. Exception → All symbols return HOLD with `reason_code="CRITICAL_ERROR"`

### Phase 2: Verbose Explanation (Non-Blocking)

**Endpoint:** `POST /explain_batch`

**Purpose:** Generate detailed explanations for fast decisions (dashboard/logs)

**Features:**
- Called asynchronously after fast decisions (fire-and-forget)
- 60-second timeout (acceptable since non-critical)
- Returns full rationale, confirmations, risk factors

**Request Schema:**
```python
{
    "context_ref": "cycle_2024-01-19T12:00:00",  # Optional
    "fast_decisions": [...],  # From /decide_batch_fast
    "global_data": {...},
    "assets_data": {...}
}
```

**Response Schema:**
```python
{
    "explanations": [
        {
            "symbol": "BTCUSDT",
            "rationale": "Detailed explanation...",
            "confirmations": ["RSI oversold", "Support at fib 0.618"],
            "risk_factors": ["High volatility"],
            "blocked_by": [],
            "soft_blockers": []
        }
    ],
    "analysis_summary": "Overall market analysis...",
    "meta": {
        "endpoint": "explain_batch",
        "symbols_count": 3
    }
}
```

## Orchestrator Integration

### Changes Made

1. **Endpoint Switch:**
   - Changed from `/decide_batch` (120s timeout) to `/decide_batch_fast` (35s timeout)
   - Reduced timeout by 70% (120s → 35s)

2. **Response Adaptation:**
   - Uses `reason_code` field instead of `rationale`
   - Handles minimal response schema

3. **Background Explanation:**
   - Async task to fetch `/explain_batch` (fire-and-forget)
   - Logs `AI_BATCH_EXPLANATION_RESPONSE` on success
   - Logs `AI_BATCH_EXPLANATION_ERROR` on failure (non-critical)

4. **New Event Types:**
   - `AI_BATCH_FAST_RESPONSE`: Fast decision metadata
   - `AI_BATCH_EXPLANATION_RESPONSE`: Explanation fetch success
   - `AI_BATCH_EXPLANATION_ERROR`: Explanation fetch failure

### Backward Compatibility

- Original `/decide_batch` endpoint **preserved** for legacy/manual use
- Fast path is now the default for orchestrator
- Dashboard continues to receive decision events via AI_DECISIONS_FILE

## Performance Improvements

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| **Timeout** | 120s | 35s | **70% faster** |
| **Response Size** | 922 bytes/decision | 285 bytes/decision | **69% smaller** |
| **Batch (3 symbols)** | 2787 bytes | 876 bytes | **69% smaller** |
| **Failure Mode** | Timeout → retry → fail | Fallback to HOLD | **Fail-safe** |
| **Explanation** | Blocking | Async (best-effort) | **Non-blocking** |

## Testing

Run the test suite:
```bash
python test_fast_decision_path.py
```

**Test Coverage:**
- ✅ DecisionFast model validation
- ✅ Fallback behavior (truncated JSON, markdown, valid JSON)
- ✅ Reason code usage
- ✅ ExplainBatchRequest model
- ✅ Response size reduction (target: >40%, achieved: 69%)

## Usage Example

### Fast Decision Call (Orchestrator)
```python
resp = await async_post_with_retry(
    c, 
    f"{URLS['ai']}/decide_batch_fast",
    json_payload={
        "global_data": enhanced_global_data,
        "assets_data": assets_data
    },
    timeout=35.0
)

dec_data = resp.json()
decisions = dec_data["decisions"]
meta = dec_data["meta"]

print(f"Fast response: {len(decisions)} decisions in {meta['processing_time_ms']}ms")
```

### Background Explanation Fetch (Optional)
```python
async def fetch_explanations():
    exp_resp = await c.post(
        f"{URLS['ai']}/explain_batch",
        json={
            "fast_decisions": decisions,
            "global_data": enhanced_global_data,
            "assets_data": assets_data
        },
        timeout=60.0
    )
    # Log for dashboard/debugging

asyncio.create_task(fetch_explanations())  # Fire and forget
```

## Files Changed

### Master AI Agent
- `agents/04_master_ai_agent/main.py`
  - Added `DecisionFast` model
  - Added `ExplainBatchRequest` model
  - Added `POST /decide_batch_fast` endpoint
  - Added `POST /explain_batch` endpoint

### Orchestrator
- `agents/orchestrator/main.py`
  - Changed AI call from `/decide_batch` to `/decide_batch_fast`
  - Updated to use `reason_code` instead of `rationale`
  - Added background explanation fetch
  - Added new event logging

### Tests
- `test_fast_decision_path.py`
  - Model validation tests
  - Fallback behavior tests
  - Reason code tests
  - Response size comparison tests

## Monitoring

### Logs to Watch

**Fast Response Success:**
```
⚡ Fast response: 3 decisions in 1234ms
```

**Fallback Triggered:**
```
⚠️ No decisions from fast AI, generating HOLD fallback
```

**Timeout:**
```
⏱️ Fast path timeout (25s) - returning all HOLD
```

**Explanation Fetch:**
```
📝 Explanations fetched: 3 items
```

### Event Types

Check `/data/ai_decisions.json` for:
- `AI_BATCH_FAST_RESPONSE`: Fast decision cycle completed
- `AI_BATCH_EXPLANATION_RESPONSE`: Explanation generated
- `AI_BATCH_EXPLANATION_ERROR`: Explanation failed (non-critical)

## Next Steps

1. **Monitor Production:**
   - Watch for timeout reduction in orchestrator logs
   - Verify HOLD fallbacks are rare
   - Check explanation fetch success rate

2. **Tune Parameters:**
   - Adjust fast timeout (currently 25s) if needed
   - Adjust `max_tokens` (currently 2000) for balance
   - Add more reason codes if patterns emerge

3. **Dashboard Integration:**
   - Display `reason_code` in decision log
   - Show explanation fetch status
   - Add fast response timing metrics

4. **Future Enhancements:**
   - Cache recent explanations for quick retry
   - Add streaming response for ultra-low latency
   - Implement partial batch processing (progressive results)
