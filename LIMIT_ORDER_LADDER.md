# Limit Order Ladder Execution Strategy - Documentation

## Overview

The Limit Order Ladder execution strategy provides advanced order placement capabilities for Bybit swap trading, enabling:

- **Market Making**: Post-only limit orders for maker fee rebates
- **Better Entry Prices**: Ladder of orders at multiple price levels
- **Reduced Slippage**: Gradual entry instead of single large market order
- **Flexible Fallback**: Automatic repricing or market order fallback

## Features

### 1. Execution Modes

#### MARKET (Default)
- Single market order for immediate execution
- Taker fees apply
- Best for urgent entries or high liquidity markets

#### LIMIT_LADDER
- Multiple limit orders placed at strategic price levels
- Post-only option for maker fee rebates
- Automatic fill monitoring and management
- Fallback strategies for unfilled orders

### 2. Ladder Price Generation

Two methods for determining ladder prices:

#### ATR-Based (Recommended)
- Uses ATR (Average True Range) for volatility-aware spacing
- Example: `ladder_atr_multipliers: [0.5, 1.0, 1.5]`
- Adapts to market volatility automatically

#### BPS-Based (Fixed)
- Uses fixed basis point offsets
- Example: `ladder_bps_offsets: [5, 10, 15]` (0.05%, 0.10%, 0.15%)
- Consistent spacing regardless of volatility

### 3. Fill Management

#### Monitoring
- Polls exchange for order fills every 5 seconds
- Tracks filled quantity vs. total target
- Respects `entry_deadline_sec` parameter (default 300s)

#### Fallback Strategies

**REPRICE** (Recommended)
- Cancels unfilled orders
- Places new orders closer to market (50% tighter)
- Retries with shorter timeout
- Balances between maker fees and execution certainty

**MARKET**
- Cancels unfilled orders
- Executes remaining quantity via market order
- Guarantees full fill but incurs taker fees

**NONE**
- Cancels unfilled orders
- Accepts partial fill
- No fallback execution

### 4. Spread & Volatility Triggers

Two-tier cycle architecture:

#### Light Cycle (30s default)
- Checks spread and volatility conditions
- Low overhead, high frequency

#### Heavy Cycle (60s default)
- Runs full AI decision pipeline
- Only executes if triggers are met:
  - Spread ≤ `SPREAD_TRIGGER_MAX_PCT` (default 0.10%)
  - ATR% ≥ `VOLATILITY_TRIGGER_MIN_ATR_PCT` (default 0.5%)

## Configuration

### Environment Variables

```bash
# System Capacity
MAX_POSITIONS=10                    # Max concurrent positions
MAX_ORDERS_PER_SYMBOL=5            # Max limit orders per symbol (ladder)

# Execution Strategy
EXECUTION_MODE=MARKET              # MARKET | LIMIT_LADDER
SPREAD_TRIGGER_MAX_PCT=0.0010      # 0.10% max spread for entry
VOLATILITY_TRIGGER_MIN_ATR_PCT=0.005  # 0.5% min ATR for entry

# Two-Tier Cycle
LIGHT_CYCLE_INTERVAL=30            # Spread/volatility check (seconds)
HEAVY_CYCLE_ENABLED=true           # Enable AI decision cycles

# Ladder Configuration (comma-separated)
LADDER_ATR_MULTIPLIERS=0.5,1.0,1.5    # ATR multipliers
LADDER_BPS_OFFSETS=5,10,15            # Basis point offsets (alternative)

# Fallback Strategy
FALLBACK_MODE=REPRICE              # REPRICE | MARKET | NONE
ENTRY_DEADLINE_SEC=300             # Deadline to complete entry (seconds)

# Safety
DRY_RUN=false                      # Set to true for testing (no real orders)
```

### Order Request Example

```python
{
    "symbol": "BTCUSDT",
    "side": "long",
    "leverage": 5.0,
    "size_pct": 0.15,
    
    # Execution strategy
    "execution_mode": "LIMIT_LADDER",
    "max_orders_per_symbol": 5,
    "post_only": True,
    "time_in_force": "GTC",
    
    # Ladder configuration
    "ladder_atr_multipliers": [0.5, 1.0, 1.5, 2.0, 2.5],
    # OR
    "ladder_bps_offsets": [5, 10, 15, 20, 25],
    
    # Fallback
    "fallback_mode": "REPRICE",
    "entry_deadline_sec": 300,
    
    # Safety constraints
    "max_spread_pct": 0.0015,      # 0.15% max spread
    "max_slippage_pct": 0.0020,    # 0.20% max slippage
    
    # Scalping parameters (optional)
    "time_in_trade_limit_sec": 2400,
    "cooldown_sec": 900
}
```

## Usage Examples

### Example 1: Conservative Ladder (Maker Focus)

```bash
# Configuration
EXECUTION_MODE=LIMIT_LADDER
FALLBACK_MODE=REPRICE
LADDER_ATR_MULTIPLIERS=0.3,0.6,0.9,1.2,1.5
ENTRY_DEADLINE_SEC=600  # 10 minutes
```

**Behavior:**
- Places 5 limit orders at 0.3x-1.5x ATR below market (long)
- Post-only orders for maker fee rebates
- Waits up to 10 minutes for fills
- Reprices unfilled orders 50% closer to market
- Accepts partial fill if still unfilled

**Use Case:** Low-urgency entries, maximize maker rebates

### Example 2: Aggressive Ladder (Fill Focus)

```bash
# Configuration
EXECUTION_MODE=LIMIT_LADDER
FALLBACK_MODE=MARKET
LADDER_BPS_OFFSETS=3,6,9
ENTRY_DEADLINE_SEC=120  # 2 minutes
```

**Behavior:**
- Places 3 limit orders at 3, 6, 9 BPS from market
- Tight spacing for higher fill probability
- Short 2-minute deadline
- Market order fallback for remaining quantity

**Use Case:** Urgent entries, guaranteed full fill

### Example 3: Market Entry (Traditional)

```bash
# Configuration
EXECUTION_MODE=MARKET
```

**Behavior:**
- Single market order
- Immediate execution
- Taker fees

**Use Case:** High urgency, high liquidity, existing behavior

## Benefits

### Cost Savings
- **Maker Fee Rebates**: Post-only orders qualify for maker rebates (typically -0.01% to -0.025%)
- **Reduced Slippage**: Ladder entry vs. single market order can save 0.05-0.20% on large orders

### Better Execution
- **Price Improvement**: Fills at multiple levels, often better than single market price
- **Market Impact**: Reduced market impact from gradual entry
- **Flexibility**: Adapt to market conditions with fallback strategies

### Risk Management
- **Spread Gating**: Only enter when spread is acceptable
- **Volatility Gating**: Only trade during sufficient volatility
- **Partial Fill Control**: Accept or reject partial fills based on strategy

## Testing

### DRY_RUN Mode

Test the strategy without risking capital:

```bash
# Enable dry run
export DRY_RUN=true

# Start system
docker-compose up -d

# Monitor logs
docker-compose logs -f orchestrator
```

**Expected Output:**
```
🔍 DRY_RUN: Would place limit order #1/5: buy 0.123 @ 49975.00
🔍 DRY_RUN: Would place limit order #2/5: buy 0.123 @ 49950.00
...
```

### Unit Tests

```bash
# Run limit order ladder tests
python3 test_limit_order_ladder.py
```

### Integration Test

```bash
# Test with real API (testnet recommended)
export BYBIT_TESTNET=true
export EXECUTION_MODE=LIMIT_LADDER
export DRY_RUN=false

# Start and monitor
docker-compose up -d
docker-compose logs -f orchestrator position_manager
```

## Monitoring

### Position Manager Logs

Key log patterns to monitor:

```bash
# Ladder placement
📊 LIMIT_LADDER mode: BTCUSDT with 5 orders
📊 Ladder prices: ['49975.00', '49950.00', '49925.00', '49900.00', '49875.00']
✅ Limit order placed #1/5: buy 0.123 @ 49975.00 (order_id=abc123)

# Fill monitoring
📊 Fill status: timeout, filled=0.246/0.615, unfilled=3
🔄 REPRICE mode: Cancelling 3 unfilled orders
🔄 Repricing with 3 orders: ['49987.50', '49975.00', '49962.50']

# Success
✅ Position opened: BTCUSDT long [intent:1a2b3c4d] mode=LIMIT_LADDER
```

### Orchestrator Logs

```bash
# Trigger checks
✅ Triggers passed for BTCUSDT: spread=OK, volatility=OK
⏸️ Triggers not met - skipping AI decision cycle (light cycle)
```

### Dashboard

Position metadata now includes execution details:
- `execution_mode`: MARKET | LIMIT_LADDER
- `spread_at_entry`: Spread percentage at entry
- `maker_taker`: maker | taker (fee classification)

## Troubleshooting

### Issue: Orders Not Filling

**Symptoms:**
- Timeout reached with 0 fills
- Unfilled orders remain after deadline

**Causes:**
1. Ladder prices too far from market
2. Low liquidity
3. Post-only rejection (price already crossed)

**Solutions:**
- Tighten ladder spacing (reduce ATR multipliers or BPS offsets)
- Use MARKET fallback mode
- Increase `entry_deadline_sec`
- Disable post_only for urgent entries

### Issue: Spread Too Wide

**Symptoms:**
- "Spread too wide" rejection
- No orders placed

**Causes:**
- Low liquidity / wide bid-ask spread
- Market volatility

**Solutions:**
- Increase `max_spread_pct` threshold
- Use MARKET mode during high volatility
- Trade more liquid pairs

### Issue: Repricing Not Working

**Symptoms:**
- Repricing triggered but still no fills

**Causes:**
- Market moved too fast
- Repricing still too far from market

**Solutions:**
- Use MARKET fallback instead of REPRICE
- Reduce initial ladder spacing
- Reduce entry deadline

## Performance Comparison

| Metric | MARKET | LIMIT_LADDER (REPRICE) | LIMIT_LADDER (MARKET) |
|--------|--------|------------------------|------------------------|
| **Fill Guarantee** | 100% | ~80-95% | 100% |
| **Avg Entry Price** | Market | Better 0.05-0.15% | Better 0.02-0.10% |
| **Execution Time** | Instant | 30-300s | 30-300s |
| **Maker Fees** | No | Yes (~60-80%) | Yes (~60-80%) |
| **Use Case** | Urgent | Cost-optimized | Balanced |

## Safety Considerations

1. **Spread Gating**: Always check spread before LIMIT_LADDER entries
2. **Max Orders**: Respect `MAX_ORDERS_PER_SYMBOL` to avoid overload
3. **Partial Fills**: Set minimum fill percentage (default 50%)
4. **DRY_RUN**: Test extensively before live trading
5. **Testnet**: Use Bybit testnet for initial validation

## Future Enhancements

Potential improvements:
- [ ] TWAP (Time-Weighted Average Price) execution
- [ ] VWAP (Volume-Weighted Average Price) execution
- [ ] Iceberg orders (hidden size)
- [ ] Smart routing (mix of maker/taker)
- [ ] Dynamic ladder adjustment based on fills
- [ ] Order book depth analysis for optimal placement

## Support

For issues or questions:
1. Check logs: `docker-compose logs -f orchestrator position_manager`
2. Review test output: `python3 test_limit_order_ladder.py`
3. Enable debug: `DEBUG_SYMBOLS=BTCUSDT,ETHUSDT`
4. Consult main README.md for general troubleshooting
