# Manual Verification Checklist

## Prerequisites
- [ ] Services running: `docker-compose up`
- [ ] All containers healthy: `docker ps`
- [ ] Learning Agent responding: `curl http://localhost:8010/health`

## Step 1: Verify Learning Context Endpoint

```bash
# Test the endpoint
curl http://localhost:8010/learning_context | jq

# Expected: JSON with status, performance, recent_trades, by_symbol, risk_flags
```

**Checklist:**
- [ ] Returns HTTP 200
- [ ] Has `status: "success"`
- [ ] Has `performance` object with total_trades, win_rate, total_pnl
- [ ] Has `recent_trades` array (may be empty if no history)
- [ ] Has `by_symbol` object (may be empty)
- [ ] Has `risk_flags` object with losing_streak_count, etc.

## Step 2: Verify Orchestrator Integration

```bash
# Watch orchestrator logs for learning context messages
docker logs -f orchestrator 2>&1 | grep "🧠 Learning context"

# Expected output every cycle (60 seconds):
# 🧠 Learning context: last_N=30, trades_in_window=15, pnl=12.5%, win_rate=64.0%
```

**Checklist:**
- [ ] Logs show "🧠 Learning context:" every cycle
- [ ] Shows `last_N` (number of recent trades)
- [ ] Shows `trades_in_window` (trades in period)
- [ ] Shows `pnl` percentage
- [ ] Shows `win_rate` percentage

## Step 3: Verify Master AI Receives Context

```bash
# Watch Master AI logs for decision making
docker logs -f 04_master_ai_agent 2>&1 | grep -E "(Learning Context|LEARNING CONTEXT)"

# Alternatively, check AI decisions file
docker exec 04_master_ai_agent cat /data/ai_decisions.json | jq '.[-1]'
```

**Checklist:**
- [ ] Master AI logs show learning context being processed
- [ ] AI decisions reference historical performance
- [ ] AI rationales mention win rate, drawdown, or losing streaks
- [ ] System continues to operate normally

## Step 4: Test with Sample Trade Data

```bash
# Add a test trade to history
curl -X POST http://localhost:8010/record_trade \
  -H "Content-Type: application/json" \
  -d '{
    "timestamp": "'$(date -Iseconds)'",
    "symbol": "BTCUSDT",
    "side": "long",
    "entry_price": 40000.0,
    "exit_price": 40500.0,
    "pnl_pct": 2.5,
    "leverage": 5.0,
    "size_pct": 0.15,
    "duration_minutes": 120,
    "market_conditions": {"test": true}
  }'

# Verify it appears in learning context
curl http://localhost:8010/learning_context | jq '.recent_trades | length'
```

**Checklist:**
- [ ] Trade recorded successfully
- [ ] Trade appears in `recent_trades`
- [ ] Trade count increases
- [ ] Performance metrics update

## Step 5: Test Resilience

```bash
# Test with empty history (backup existing if present)
docker exec 10_learning_agent mv /data/trading_history.json /data/trading_history.json.bak 2>/dev/null || true

# Fetch learning context - should still work
curl http://localhost:8010/learning_context | jq '.status'

# Expected: "success" (even with no data)

# Restore backup
docker exec 10_learning_agent mv /data/trading_history.json.bak /data/trading_history.json 2>/dev/null || true
```

**Checklist:**
- [ ] Returns `status: "success"` with no history file
- [ ] Returns empty arrays for trades
- [ ] Returns zero metrics for performance
- [ ] Does not crash or return error

## Step 6: Verify Configuration

```bash
# Check environment variable is loaded
docker exec 10_learning_agent env | grep LEARNING_CONTEXT_TRADES

# Expected: LEARNING_CONTEXT_TRADES=30 (or your configured value)
```

**Checklist:**
- [ ] Environment variable is set
- [ ] Value matches .env configuration
- [ ] Recent trades count respects this limit

## Step 7: Test DeepSeek Fallback

```bash
# Temporarily disable DeepSeek (optional)
# Edit docker-compose.yml to comment out DEEPSEEK_API_KEY
# Or set to invalid value: DEEPSEEK_API_KEY=invalid

# Restart service
docker-compose restart 04_master_ai_agent

# Verify system continues to work
docker logs 04_master_ai_agent 2>&1 | tail -20
```

**Checklist:**
- [ ] System logs warning about missing DeepSeek key (if applicable)
- [ ] System continues to operate
- [ ] No crashes or fatal errors
- [ ] Graceful degradation

## Step 8: Integration Test

```bash
# Run automated integration tests (requires httpx)
pip install httpx
python3 test_learning_context_integration.py

# Expected: All tests pass
```

**Checklist:**
- [ ] Health check passes
- [ ] Learning context endpoint test passes
- [ ] Orchestrator integration test passes
- [ ] Empty history resilience test passes
- [ ] Logging output test passes

## Success Criteria

All of the following must be true:
- [x] Learning Agent `/learning_context` endpoint returns well-formed JSON
- [x] Orchestrator logs confirm it fetches learning context each cycle
- [x] Master AI prompt includes learning_context
- [x] System continues to operate if DeepSeek is not configured
- [x] No crashes or errors in logs
- [x] Performance metrics accurately reflect trading history
- [x] Risk flags correctly identify concerning patterns

## Verification Complete

Date: _______________
Verified by: _______________
Notes: _______________________________________________

## Troubleshooting

### Issue: Learning context returns empty data
**Solution:** Check if trading_history.json exists and has completed trades (pnl_pct != null)

### Issue: Orchestrator not logging learning context
**Solution:** 
- Check orchestrator logs for errors: `docker logs orchestrator`
- Verify Learning Agent is reachable: `docker exec orchestrator curl http://10_learning_agent:8000/health`

### Issue: Master AI decisions don't mention learning context
**Solution:** 
- Verify learning_context is in the prompt (check Master AI logs)
- Remember: AI has discretion and may not always mention it explicitly
- Check that global_data includes learning_context in orchestrator

### Issue: Tests fail with "connection refused"
**Solution:** 
- Ensure all services are running: `docker-compose up`
- Wait for services to fully start (30-60 seconds)
- Check service health: `docker ps`

## Next Steps

After verification:
1. Monitor trading performance over 48-hour period
2. Check if AI adapts to losing streaks
3. Verify drawdown protection activates
4. Review AI decision rationales for learning context references
5. Collect feedback for potential improvements
