# Testing Guide: Learning Agent Integration

This guide explains how to verify the Learning Agent integration is working correctly.

## Prerequisites

1. Ensure all containers are running:
   ```bash
   docker-compose up -d
   ```

2. Verify Learning Agent is active:
   ```bash
   curl http://localhost:8010/health
   ```
   Expected output: `{"status":"active","evolution_interval_hours":48,"min_trades_for_evolution":5}`

## Test 1: Verify Trade Recording

### Manual Trade Recording Test

Send a test trade to the Learning Agent:

```bash
curl -X POST http://localhost:8010/record_trade \
  -H "Content-Type: application/json" \
  -d '{
    "timestamp": "2025-12-12T16:00:00",
    "symbol": "ETHUSDT",
    "side": "long",
    "entry_price": 3800.0,
    "exit_price": 3850.0,
    "pnl_pct": 6.5,
    "leverage": 5.0,
    "size_pct": 0.15,
    "duration_minutes": 120,
    "market_conditions": {"test": true}
  }'
```

Expected output: `{"status":"success","message":"Trade recorded"}`

### Verify Data Persistence

Check if the trade was saved:

```bash
# If using Docker, check inside the container
docker exec -it 10_learning_agent cat /data/trading_history.json
```

The file should contain the recorded trade.

## Test 2: Verify Learning Insights Consultation

### Check Current Parameters

```bash
curl http://localhost:8010/current_params
```

Expected output:
```json
{
  "status": "default" or "evolved",
  "version": "v0.0" or "v1.0+",
  "params": {
    "rsi_overbought": 70,
    "rsi_oversold": 30,
    ...
  }
}
```

### Check Performance Metrics

```bash
curl http://localhost:8010/performance
```

Expected output:
```json
{
  "status": "success",
  "period_hours": 48,
  "performance": {
    "total_trades": 0 or more,
    "win_rate": 0.0 to 1.0,
    "total_pnl": number,
    ...
  }
}
```

## Test 3: Verify Position Manager Records Trades

### Close a Test Position

When a position is closed (manually or automatically), the Position Manager should:
1. Calculate the PnL
2. Send trade data to Learning Agent
3. Log: `📚 Trade recorded for learning: SYMBOL SIDE PnL=X.XX%`

Check the Position Manager logs:
```bash
docker logs 07_position_manager | grep "Trade recorded for learning"
```

## Test 4: Verify Master AI Consults Learning Agent

### Check Master AI Logs

When Master AI makes decisions, it should:
1. Fetch learning insights
2. Include performance data in decision-making
3. Log: `📚 Using evolved params vX.X`

Check the Master AI logs:
```bash
docker logs 04_master_ai_agent | grep "Using evolved params"
```

Or check for warnings if insights are unavailable:
```bash
docker logs 04_master_ai_agent | grep "Could not get learning insights"
```

## Test 5: Trigger Evolution Manually

After recording at least 5 trades, trigger evolution:

```bash
curl -X POST http://localhost:8010/trigger_evolution
```

Expected output: `{"status":"success","message":"Evolution cycle completed"}`

### Check Evolution Results

```bash
# Check if evolved_params.json was created
docker exec -it 10_learning_agent cat /data/evolved_params.json

# Check evolution log
curl http://localhost:8010/evolution_log
```

## Test 6: Verify API Costs Tracking

```bash
docker exec -it 10_learning_agent cat /data/api_costs.json
```

The file should contain API call logs with token counts.

## Expected Behavior Summary

1. **Position Manager**: 
   - Records trades when positions close
   - Works for manual close, SL/TP, reverse, hard stop

2. **Learning Agent**:
   - Saves trades to `/data/trading_history.json`
   - Evolves parameters after minimum trades
   - Uses DeepSeek API for analysis

3. **Master AI**:
   - Fetches learning insights before decisions
   - Uses evolved parameters in prompts
   - Includes performance metrics in decision context

## Troubleshooting

### Issue: "Failed to record trade for learning"

**Cause**: Learning Agent is not reachable from Position Manager.

**Solution**: 
- Check if Learning Agent container is running: `docker ps | grep 10_learning_agent`
- Check network connectivity: `docker exec -it 07_position_manager ping 10_learning_agent`

### Issue: "DeepSeek client not configured"

**Cause**: DEEPSEEK_API_KEY is not set.

**Solution**:
- Add `DEEPSEEK_API_KEY=your_key_here` to `.env` file
- Restart containers: `docker-compose restart`

### Issue: "Could not get learning insights"

**Cause**: Learning Agent is not responding.

**Solution**:
- Check Learning Agent health: `curl http://localhost:8010/health`
- Check Learning Agent logs: `docker logs 10_learning_agent`

## Success Criteria

✅ All tests pass
✅ Trades are recorded in `/data/trading_history.json`
✅ Master AI logs show "Using evolved params"
✅ No errors in container logs related to Learning Agent
✅ API costs are tracked in `/data/api_costs.json`
