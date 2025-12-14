# Critical Position Management Testing Guide

This guide explains how to test the new critical position management functionality.

## Overview

The implementation adds:
1. **Master AI Agent**: New `/manage_critical_positions` endpoint
2. **Orchestrator**: Integration with critical position management
3. **Utility Script**: `tools/manage_positions.py` for testing

## Components Changed

### 1. Master AI Agent (`agents/04_master_ai_agent/main.py`)

**New Endpoint**: `POST /manage_critical_positions`

**Request Model**:
```json
{
  "positions": [
    {
      "symbol": "BTCUSDT",
      "side": "long",
      "entry_price": 42000.0,
      "mark_price": 40000.0,
      "leverage": 5.0,
      "size": 0.1,
      "pnl": -100.0,
      "is_disabled": false
    }
  ],
  "portfolio_snapshot": {
    "equity": 1000.0,
    "free_balance": 500.0
  }
}
```

**Response Model**:
```json
{
  "actions": [
    {
      "symbol": "BTCUSDT",
      "action": "CLOSE",
      "confidence": 75,
      "rationale": "Loss too severe, no clear reversal signals",
      "score_breakdown": {
        "technical_score": 50,
        "loss_severity": 95,
        "trend_alignment": 0,
        "volume_confirmation": 0
      },
      "loss_pct_with_leverage": -23.81,
      "confirmations_count": 2,
      "confirmations": ["RSI 1h oversold (28.5)", "Volume in aumento"]
    }
  ],
  "meta": {
    "timeout_occurred": false,
    "processing_time_ms": 450,
    "total_positions": 1
  }
}
```

**Key Features**:
- ✅ Computes `loss_pct_with_leverage` consistently for long/short positions
- ✅ Fast path using portfolio snapshot + technical analyzer multi-timeframe
- ✅ Hard timeout (20s) around LLM calls with deterministic fallback
- ✅ Enforces constraints:
  - Disabled symbols → never REVERSE
  - Prefer CLOSE over REVERSE unless confirmations >= 4
- ✅ Returns structured JSON with meaningful `score_breakdown`

### 2. Orchestrator (`agents/orchestrator/main.py`)

**Changes**:
- ✅ Ensures `positions_losing` is initialized before use
- ✅ Adds critical position management block with logging
- ✅ Sets 60s timeout for Master AI endpoint call
- ✅ Executes CLOSE/REVERSE actions via position manager
- ✅ Supports DRY_RUN mode (set `DRY_RUN=true` env var)
- ✅ Skips opening new positions when critical management runs

**New Environment Variable**:
```bash
DRY_RUN=false  # Set to "true" to log actions without executing
```

## Testing

### Prerequisites

1. **Docker Compose Setup**:
   ```bash
   # Ensure you have the .env file configured
   cp .env.example .env
   # Edit .env with your API keys
   ```

2. **Build and Start Services**:
   ```bash
   docker-compose up -d --build
   ```

### Test 1: Unit Tests (Logic Validation)

Run the unit tests to verify core logic:

```bash
python3 test_critical_positions.py
```

**Expected Output**:
```
============================================================
  Critical Position Management - Unit Tests
============================================================

⚠️ Test 1 skipped: Cannot import models (missing dependencies)
✅ Test 2 passed: Loss calculations are correct
✅ Test 3 passed: Confirmation logic works correctly
✅ Test 4 passed: Constraint logic works correctly

============================================================
  Results: 4 passed, 0 failed
============================================================
```

### Test 2: Endpoint Testing (From Host)

Test the Master AI endpoint directly from your host machine:

```bash
# Single position test
python3 tools/manage_positions.py --host localhost --port 8004

# Multiple positions test
python3 tools/manage_positions.py --host localhost --port 8004 --multi

# Custom position test
python3 tools/manage_positions.py \
  --host localhost --port 8004 \
  --symbol ETHUSDT \
  --side short \
  --entry 2200 \
  --mark 2300 \
  --leverage 5
```

**Expected Output**:
```
============================================================
  Master AI - Critical Position Management Test
============================================================

🔗 Calling: http://localhost:8004/manage_critical_positions
📤 Request body:
{
  "positions": [...],
  "portfolio_snapshot": {...}
}

✅ Response (Status 200):
{
  "actions": [...],
  "meta": {...}
}

============================================================
  Summary
============================================================

📊 Total actions: 1
⏱️  Processing time: 450ms
⚠️  Timeout occurred: False

🎯 Actions breakdown:
  • BTCUSDT: CLOSE (loss: -23.81%, confidence: 75%)

✅ Test completed successfully!
```

### Test 3: Endpoint Testing (From Docker)

Test from within the Docker network:

```bash
# Enter the orchestrator container
docker exec -it orchestrator bash

# Run test from inside container
python3 /home/runner/work/trading-agent-system/trading-agent-system/tools/manage_positions.py \
  --host 04_master_ai_agent --port 8000
```

### Test 4: Integration Testing (Orchestrator)

Monitor orchestrator logs to see critical position management in action:

```bash
# Follow orchestrator logs
docker logs -f orchestrator

# In another terminal, trigger a critical position scenario
# (This requires real positions with losses > REVERSE_THRESHOLD)
```

**Expected Log Output**:
```
[15:30] 📊 Position check: 3/3 posizioni aperte
        🔥 CRITICAL: 1 posizioni in perdita oltre soglia!
        ⚠️ BTCUSDT long: -23.81%
        📞 Calling Master AI /manage_critical_positions...
        ✅ MGMT Response: 1 actions, 450ms
        🎯 ACTION: BTCUSDT → CLOSE (loss=-23.81%, conf=75%)
        🔒 Closing BTCUSDT...
        ✅ Close result: {"status": "success", ...}
        🛑 Critical management ran, skipping new position logic this cycle
```

### Test 5: DRY_RUN Mode

Test without executing actual trades:

```bash
# Stop orchestrator
docker-compose stop orchestrator

# Add DRY_RUN to .env
echo "DRY_RUN=true" >> .env

# Restart orchestrator
docker-compose up -d orchestrator

# Watch logs
docker logs -f orchestrator
```

**Expected Log Output (DRY_RUN)**:
```
[15:30] 📊 Position check: 3/3 posizioni aperte
        🔥 CRITICAL: 1 posizioni in perdita oltre soglia!
        ...
        🎯 ACTION: BTCUSDT → CLOSE (loss=-23.81%, conf=75%)
        🔍 DRY_RUN mode: azioni non eseguite
        🛑 Critical management ran, skipping new position logic this cycle
```

## Validation Checklist

- [ ] `/manage_critical_positions` endpoint returns 200 with proper JSON structure
- [ ] `loss_pct_with_leverage` is correctly calculated for long positions
- [ ] `loss_pct_with_leverage` is correctly calculated for short positions
- [ ] Disabled symbols never return REVERSE action
- [ ] REVERSE is only returned when confirmations >= 4
- [ ] Orchestrator logs show MGMT actions correctly
- [ ] Orchestrator no longer crashes with UnboundLocalError
- [ ] Orchestrator skips new position logic when critical management runs
- [ ] DRY_RUN mode logs actions without executing them
- [ ] CLOSE actions are executed via position manager
- [ ] REVERSE actions close old position and open opposite position

## Troubleshooting

### Issue: Connection refused

**Solution**: Ensure services are running:
```bash
docker-compose ps
```

### Issue: DEEPSEEK_API_KEY not set

**Solution**: Add to .env file:
```bash
DEEPSEEK_API_KEY=your_api_key_here
```

### Issue: Timeout errors

**Solution**: Check network connectivity and increase timeout:
```bash
# In orchestrator/main.py, increase timeout value
timeout=90.0  # Instead of 60.0
```

### Issue: No critical positions detected

**Solution**: Lower REVERSE_THRESHOLD for testing:
```bash
# In orchestrator/main.py
REVERSE_THRESHOLD = 0.5  # Instead of 2.0 (for testing only!)
```

## Performance Metrics

Expected response times:
- Single position: 200-500ms
- Multiple positions (3): 800-1500ms
- With LLM timeout: ~20000ms (fallback to deterministic decision)

## Security Considerations

1. **LLM Timeout**: Hard 20s timeout prevents unbounded blocking
2. **Fallback Logic**: Deterministic fallback ensures system stability
3. **Constraint Enforcement**: Disabled symbols protection
4. **DRY_RUN Mode**: Safe testing without actual trades

## Next Steps

After testing is complete:
1. Monitor production logs for critical position scenarios
2. Tune REVERSE_THRESHOLD based on market conditions
3. Adjust confirmation thresholds if needed
4. Review and optimize LLM prompts for better decisions
5. Add more technical indicators for confirmation logic

## Support

For issues or questions:
- Check logs: `docker logs <container_name>`
- Review code: `agents/04_master_ai_agent/main.py`, `agents/orchestrator/main.py`
- Test endpoint: `tools/manage_positions.py`
