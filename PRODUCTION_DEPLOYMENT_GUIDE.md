# Fast Decision Path - Production Deployment Guide

## Quick Start

The fast decision path is **already enabled by default** in the orchestrator. No configuration changes are needed to start using it.

## What Changed

### Before (Old Behavior)
```
Orchestrator → /decide_batch (120s timeout) → Parse full JSON → Execute
                     ↓
                 TIMEOUT (frequently)
```

### After (New Behavior)
```
Orchestrator → /decide_batch_fast (35s timeout) → Parse minimal JSON → Execute
                     ↓                                    ↓
               Fire & forget:                    Fast & reliable
          /explain_batch (60s timeout)
              for dashboard logs
```

## Environment Variables (Optional Tuning)

### Master AI Agent (04_master_ai_agent)

```bash
# Fast decision endpoint timeout (default: 25s)
FAST_DECISION_TIMEOUT_SEC=25.0

# Max tokens to prevent truncation (default: 2000)
FAST_DECISION_MAX_TOKENS=2000

# Explanation endpoint timeout (default: 60s)
EXPLANATION_TIMEOUT_SEC=60.0
```

### Orchestrator

```bash
# Timeout for calling fast decision endpoint (default: 35s)
FAST_DECISION_CALL_TIMEOUT_SEC=35.0
```

## Monitoring

### Key Metrics to Watch

1. **Fast Response Time**
   Look for log entries like:
   ```
   ⚡ Fast response: 3 decisions in 1234ms
   ```
   - Expected: 1-3 seconds for normal responses
   - Concern if: > 20 seconds consistently

2. **Fallback Frequency**
   Look for log entries like:
   ```
   ⚠️ No decisions from fast AI, generating HOLD fallback
   ```
   - Expected: Rare (< 1% of cycles)
   - Concern if: > 5% of cycles

3. **Timeout Events**
   Look for log entries like:
   ```
   ⏱️ Fast path timeout (25s) - returning all HOLD
   ```
   - Expected: Very rare (< 0.1% of cycles)
   - Concern if: Multiple times per day

4. **Event Types in `/data/ai_decisions.json`**
   - `AI_BATCH_FAST_RESPONSE`: Should appear every cycle
   - `AI_BATCH_EXPLANATION_RESPONSE`: Should appear most cycles
   - `AI_BATCH_EXPLANATION_ERROR`: Acceptable occasionally

### Dashboard Integration

The dashboard can now display:
- `reason_code` field for quick decision understanding
- Processing time from `meta.processing_time_ms`
- Fast vs. full response indicator

Example decision in `/data/ai_decisions.json`:
```json
{
  "type": "AI_BATCH_FAST_RESPONSE",
  "status": "success",
  "timestamp": "2024-01-19T21:00:00Z",
  "details": {
    "decisions_count": 3,
    "processing_time_ms": 2341,
    "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
  }
}
```

## Troubleshooting

### Problem: Still seeing timeouts

**Possible causes:**
1. Network latency to DeepSeek API
2. DeepSeek API overload
3. Timeout too aggressive

**Solutions:**
```bash
# Increase timeouts slightly
export FAST_DECISION_TIMEOUT_SEC=30.0
export FAST_DECISION_CALL_TIMEOUT_SEC=40.0
```

### Problem: Many HOLD fallbacks

**Possible causes:**
1. DeepSeek response truncation still occurring
2. Token limit too low
3. Prompt too complex

**Solutions:**
```bash
# Increase max tokens
export FAST_DECISION_MAX_TOKENS=3000
```

### Problem: Explanations not appearing

**Possible causes:**
1. Explanation fetch timing out
2. Network issues

**Solutions:**
```bash
# Increase explanation timeout
export EXPLANATION_TIMEOUT_SEC=90.0
```

**Note:** This is non-critical - decisions still execute without explanations.

## Performance Expectations

### Normal Operation
- **Fast response time**: 1-3 seconds
- **Success rate**: > 99%
- **Fallback rate**: < 1%
- **Timeout rate**: < 0.1%
- **Explanation fetch success**: > 90%

### During DeepSeek API Issues
- **Fast response time**: 5-20 seconds
- **Success rate**: > 95% (with fallbacks)
- **Fallback rate**: 1-5%
- **Timeout rate**: 0.1-1%
- **Explanation fetch success**: 50-80%

**Key benefit:** System continues operating even during API issues, returning safe HOLD decisions.

## Rolling Back (If Needed)

If you need to revert to the old behavior temporarily:

### Option 1: Use old endpoint directly (requires code change)
In `agents/orchestrator/main.py`, change:
```python
resp = await async_post_with_retry(c, f"{URLS['ai']}/decide_batch_fast", ...)
```
back to:
```python
resp = await async_post_with_retry(c, f"{URLS['ai']}/decide_batch", ...)
```

### Option 2: Increase timeouts to match old behavior
```bash
export FAST_DECISION_TIMEOUT_SEC=60.0
export FAST_DECISION_CALL_TIMEOUT_SEC=120.0
export FAST_DECISION_MAX_TOKENS=8000
```

**Note:** This defeats the purpose of the fast path but maintains compatibility.

## Testing in Staging

Before deploying to production, test with:

1. **Smoke test:**
   ```bash
   # Watch orchestrator logs
   docker logs -f orchestrator
   
   # Look for "⚡ Fast response" messages
   ```

2. **Load test:**
   ```bash
   # Reduce cycle interval temporarily
   export CYCLE_INTERVAL=30
   
   # Monitor for 1 hour
   # Check fallback rate < 5%
   ```

3. **Failure simulation:**
   ```bash
   # Set aggressive timeout
   export FAST_DECISION_TIMEOUT_SEC=5.0
   
   # Should see HOLD fallbacks but no crashes
   ```

## Success Indicators

✅ Orchestrator logs show consistent fast responses (1-3s)  
✅ No more `httpx.ReadTimeout` errors in orchestrator  
✅ Fallback rate < 1%  
✅ All trading cycles complete successfully  
✅ Dashboard shows decision events for all cycles  

## Support

If issues persist after tuning:
1. Check network latency to DeepSeek API
2. Review DeepSeek API status page
3. Consider temporary rollback (see above)
4. Report issue with logs showing:
   - Fast response times
   - Fallback frequency
   - Timeout events
   - Network diagnostics

## Advanced: A/B Testing

To compare old vs. new behavior in production:

1. Run two orchestrator instances:
   - Instance A: Using fast path (default)
   - Instance B: Using old path (manual change)

2. Compare metrics:
   - Decision latency
   - Timeout frequency
   - Trade execution success rate
   - Decision quality (win rate)

3. Monitor for 24-48 hours

Expected outcome: Fast path shows 70% faster responses with equal decision quality.
