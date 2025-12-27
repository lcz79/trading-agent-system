# Scalping/Intraday Refactor - Implementation Status

## Goal
Refactor the trading system into a coherent **intraday/scalping-first** architecture where the **Master AI is the single decision authority** and other services act deterministically for execution and risk enforcement.

## ✅ Completed Work

### 1. Backup & Preparation
- ✅ Created backup branch: `backup/pre-scalping-refactor-2025-12-27`
- ✅ Created snapshot folder: `backup_snapshot/2025-12-27/` with all in-scope files
- ✅ Updated `.gitignore` to exclude backups

### 2. Critical Bug Fixes
- ✅ **Fixed indentation bug in Master AI** (`agents/04_master_ai_agent/main.py:750`)
  - `enhanced_system_prompt` was defined inside if-block causing NameError
  - Moved outside to ensure it's always defined

### 3. Scalping Schema (Master AI)
- ✅ **Updated Decision Pydantic model** with scalping fields:
  - `tp_pct`: Take profit percentage (e.g., 0.02 for 2%)
  - `sl_pct`: Stop loss percentage (e.g., 0.015 for 1.5%)
  - `time_in_trade_limit_sec`: Max holding time in seconds
  - `cooldown_sec`: Cooldown period after close (per symbol+direction)
  - `trail_after_tp_reached`: Enable trailing after TP reached (optional)
  - `trail_activation_roi`: ROI threshold to activate trailing (optional)

- ✅ **Updated formatted_system_prompt.txt**
  - Added deprecation notice (actual prompt is in main.py)
  - Documented new scalping schema and requirements

### 4. Unified State Management
- ✅ **Created `agents/shared/trading_state.py`** - Single source of truth
  - `OrderIntent`: Tracks intents with `intent_id` for idempotency
  - `Cooldown`: Manages cooldowns with expiration checks
  - `PositionMetadata`: Tracks open positions with time-in-trade
  - `TrailingStopState`: Manages trailing stop state
  - Thread-safe operations with file locking
  - Singleton pattern via `get_trading_state()`

### 5. Orchestrator Refactoring
- ✅ **Removed silent AI param clamping**
  - Deleted `clamp_ai_params()` function
  - Added `validate_ai_params()` that warns but doesn't modify
  - Orchestrator now trusts AI decisions without override

- ✅ **Added idempotency support**
  - Generates `intent_id` (UUID) for each order
  - Passes `intent_id` to Position Manager

- ✅ **Passes scalping parameters**
  - Extracts tp_pct, sl_pct, time_in_trade_limit_sec, etc. from AI decisions
  - Forwards all parameters to Position Manager in open_position payload

## 🚧 Remaining Work

### 6. Master AI System Prompt Update
**Status**: Not started  
**Priority**: High  
**Tasks**:
- [ ] Update `SYSTEM_PROMPT` constant with scalping-focused guidance:
  - Prioritize 1m/5m/15m timeframes (optional 1h confirmation)
  - Set target profits: 1-3% leveraged ROI
  - Set stop loss: 1-2% leveraged ROI  
  - Set max holding time: 1-4 hours
  - **Disable REVERSE by default** (too risky for scalping)
  
- [ ] Update output schema in prompt to include scalping params:
  ```json
  {
    "tp_pct": 0.02,
    "sl_pct": 0.015,
    "time_in_trade_limit_sec": 3600,
    "cooldown_sec": 900,
    "trail_activation_roi": 0.01
  }
  ```

- [ ] Add examples with scalping parameters in prompt

### 7. Position Manager Integration
**Status**: Not started  
**Priority**: High  
**Tasks**:

#### A) Idempotency
- [ ] Update `open_position` endpoint to accept `intent_id` parameter
- [ ] Check if `intent_id` already exists in trading_state before executing
- [ ] Store executed `intent_id` with exchange order ID in trading_state
- [ ] Return existing result if `intent_id` already processed (idempotent)

#### B) Scalping Parameters Support
- [ ] Accept and use `tp_pct`, `sl_pct` from request
- [ ] Set TP/SL at order placement (if exchange supports) or immediately after
- [ ] Store `time_in_trade_limit_sec` in position metadata via trading_state

#### C) Time-Based Exit
- [ ] Create background job that checks for expired positions
- [ ] Query `trading_state.get_expired_positions()` every 30 seconds
- [ ] Close positions that exceed `time_in_trade_limit_sec`
- [ ] Log reason: "Time limit exceeded (scalping mode)"

#### D) Cooldown Integration
- [ ] On position close, add cooldown to trading_state:
  ```python
  from agents.shared.trading_state import get_trading_state, Cooldown
  
  state = get_trading_state()
  state.add_cooldown(Cooldown(
      symbol=symbol,
      direction=direction,
      closed_at=datetime.utcnow().isoformat(),
      reason="Position closed",
      cooldown_sec=cooldown_sec or 900  # default 15 min
  ))
  ```

#### E) Reconciliation Checks
- [ ] Before opening: verify position doesn't already exist on exchange
- [ ] After opening: verify position was created successfully
- [ ] After closing: verify position was closed successfully
- [ ] Log discrepancies and retry if needed

#### F) Disable/Remove REVERSE Logic
- [ ] Remove automatic REVERSE behavior (inappropriate for scalping)
- [ ] Or gate behind explicit config flag: `ENABLE_REVERSE=false` (default)
- [ ] Update `analyze_reverse` endpoint to return CLOSE or HOLD only (no REVERSE)

### 8. Orchestrator State Integration
**Status**: Not started  
**Priority**: Medium  
**Tasks**:
- [ ] Use `trading_state.is_in_cooldown(symbol, direction)` to check cooldowns
- [ ] Log active cooldowns in decision context
- [ ] Store intent to trading_state after generating `intent_id`:
  ```python
  from agents.shared.trading_state import get_trading_state, OrderIntent
  
  state = get_trading_state()
  state.add_intent(OrderIntent(
      intent_id=intent_id,
      symbol=sym,
      action=action,
      leverage=leverage,
      size_pct=size_pct,
      tp_pct=tp_pct,
      sl_pct=sl_pct,
      time_in_trade_limit_sec=time_in_trade_limit_sec,
      cooldown_sec=cooldown_sec
  ))
  ```

### 9. Master AI Cooldown Integration
**Status**: Not started  
**Priority**: Medium  
**Tasks**:
- [ ] Replace `load_recent_closes()` with `trading_state.get_active_cooldowns()`
- [ ] Format cooldowns for prompt context
- [ ] Remove dependency on `RECENT_CLOSES_FILE`

### 10. One-Way Mode Verification
**Status**: Not started  
**Priority**: Medium  
**Tasks**:
- [ ] Verify `HEDGE_MODE=false` in Position Manager
- [ ] Ensure `positionIdx=0` for all orders (One-Way mode)
- [ ] Add validation: reject if trying to open opposite direction with existing position
- [ ] Document One-Way mode requirement in README

### 11. Testing
**Status**: Not started  
**Priority**: High  
**Tasks**:
- [ ] Test Pydantic validation with scalping fields
- [ ] Test idempotency: retry same `intent_id` shouldn't duplicate order
- [ ] Test cooldown persistence across restarts
- [ ] Test time-based exits trigger correctly
- [ ] Test that REVERSE is disabled
- [ ] Run existing test suite to check for regressions

### 12. Documentation
**Status**: Not started  
**Priority**: Medium  
**Tasks**:
- [ ] Create `SCALPING_MODE.md` with:
  - Architecture overview
  - Scalping parameters guide
  - One-Way mode explanation
  - Idempotency mechanism
  
- [ ] Update `README.md` with scalping mode info

- [ ] Document trading_state.json structure:
  ```json
  {
    "version": "1.0.0",
    "last_updated": "ISO timestamp",
    "order_intents": {
      "uuid": {OrderIntent}
    },
    "cooldowns": [Cooldown],
    "position_metadata": {
      "symbol_direction": {PositionMetadata}
    },
    "trailing_stops": {
      "symbol_direction": {TrailingStopState}
    }
  }
  ```

## Architecture Summary

### Before Refactor
- **Multi-authority**: Master AI, Position Manager, Orchestrator all made strategic decisions
- **Silent overrides**: Orchestrator clamped AI parameters without transparency
- **Scattered state**: Multiple JSON files (recent_closes, cooldown, trailing_state)
- **No idempotency**: Retries could create duplicate orders
- **No scalping support**: Lacked time limits, cooldowns, precise TP/SL

### After Refactor
- **Single authority**: Master AI makes ALL trading decisions
- **Transparent validation**: Orchestrator validates but trusts AI
- **Unified state**: Single `/data/trading_state.json` file
- **Idempotency**: `intent_id` prevents duplicate orders
- **Scalping-first**: 1-3% targets, 1-2% SL, 1-4h time limits, cooldowns
- **One-Way mode**: Single position per symbol (no hedging)
- **Deterministic execution**: Position Manager executes intents faithfully

## Files Modified

1. **agents/04_master_ai_agent/main.py**
   - Fixed critical indentation bug
   - Added scalping fields to Decision model
   - (TODO: Update SYSTEM_PROMPT)

2. **agents/04_master_ai_agent/formatted_system_prompt.txt**
   - Added deprecation notice
   - Documented new schema

3. **agents/orchestrator/main.py**
   - Removed `clamp_ai_params()`
   - Added `validate_ai_params()`
   - Added `intent_id` generation
   - Passes scalping params to Position Manager

4. **agents/shared/trading_state.py** (NEW)
   - Unified state management module

5. **.gitignore**
   - Excluded backup_snapshot/
   - Excluded *.backup* files

## Next Steps

**Immediate priorities** (in order):
1. Update Master AI `SYSTEM_PROMPT` with scalping guidance
2. Implement idempotency in Position Manager
3. Implement time-based exits in Position Manager
4. Disable/remove REVERSE logic
5. Integration testing

## Notes

- Keep using Technical, Fibonacci, Gann, News, Forecaster agents as **context inputs only**
- They provide signals, but Master AI makes the final decision
- REVERSE is **disabled by default** for scalping (too risky for fast trades)
- One-Way mode is **required** (no simultaneous long/short on same symbol)

---

**Last Updated**: 2025-12-27  
**Status**: Phase 1-5 Complete, Phase 6-12 In Progress
