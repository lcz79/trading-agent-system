# AI Decision Rationale Improvements - Summary

## Problem Statement
The bot sometimes outputs contradictory rationale such as:
- Listing 5 confirmations for opening SHORT, but then saying it will not open LONG and concluding HOLD
- Risk constraints mixed with setup confirmations in free-text, leading to confusing and incorrect explanations

## Solution Implemented

### 1. Structured Decision Fields

Added three new fields to the Decision model:

```python
setup_confirmations: List[str]  # Confirmations specific to the direction being evaluated
blocked_by: List[str]           # Explicit blocking reasons (INSUFFICIENT_MARGIN, MAX_POSITIONS, etc.)
direction_considered: str       # LONG, SHORT, or NONE
```

### 2. Guardrail System

Implemented `enforce_decision_consistency()` that:
- Ensures `direction_considered` matches the action (OPEN_LONG → LONG, OPEN_SHORT → SHORT)
- Forces action to HOLD when `blocked_by` is present
- Infers missing structured fields for backward compatibility
- Warns about contradictory rationales in logs

### 3. Enhanced System Prompt

Updated the AI prompt to enforce:
- Structured decision flow: Analyze → Identify Direction → Collect Confirmations → Apply Constraints → Decide
- Clear separation between setup confirmations and risk factors
- Explicit blocked_by field when constraints prevent action
- Direction-specific reasoning (SHORT setup must have SHORT confirmations)

### 4. Orchestrator Enhancement

Enhanced payload to include:
- `max_positions`, `positions_open_count` - Position limits
- `wallet.available_for_new_trades` - Available margin
- `drawdown_pct` - Current system drawdown
- Constraints clearly communicated to AI for structured blocking

### 5. Dashboard Updates

Dashboard now displays:
- `blocked_by` reasons (red badge)
- `direction_considered` (colored by direction)
- `setup_confirmations` (expandable list)
- Backward compatible with old decisions

## Before vs After Examples

### Before (Contradictory)
```json
{
  "action": "HOLD",
  "rationale": "5 confirmazioni per SHORT trovate: RSI > 70, trend bearish 1h/4h, 
                resistenza Fibonacci... ma pattern BTC long recente in perdita quindi 
                non aprirò LONG.",
  "confirmations": ["RSI > 70", "Trend bearish", "Fibonacci resistance", "News negative", "Forecast down"]
}
```
**Problem**: Lists 5 SHORT confirmations but mentions not opening LONG - confusing!

### After (Coherent)
```json
{
  "action": "HOLD",
  "direction_considered": "SHORT",
  "setup_confirmations": [
    "RSI > 70 (ipercomprato)",
    "Trend bearish su 1h e 4h",
    "Resistenza Fibonacci rifiutata",
    "News sentiment negativo",
    "Forecast prevede calo"
  ],
  "blocked_by": ["INSUFFICIENT_MARGIN"],
  "rationale": "Setup SHORT valido con 5 conferme. Bloccato da margine insufficiente per aprire.",
  "risk_factors": ["Recent BTC long loss (non blocker, solo risk factor)"]
}
```
**Improvement**: Clear that SHORT setup is valid, but blocked by margin. Risk factors separated.

## Acceptance Criteria Validation

✅ **Criterion 1**: Decision with 5 confirmations for SHORT returns either OPEN_SHORT or HOLD with `blocked_by` explaining why
- Validated in `test_acceptance_criteria.py` test 1A and 1B

✅ **Criterion 2**: No mismatched text like 'pattern BTC long' as reason to block OPEN_SHORT setup
- Risk factors clearly separated from setup confirmations
- Guardrail warns about contradictory rationales
- Validated in test 2A and 2B

✅ **Criterion 3**: Backward compatible - dashboard renders old decisions without errors
- Old decisions automatically enhanced with inferred fields
- All new fields are optional
- Validated in test 3A and 3B

## Test Results

### Unit Tests (`test_master_ai_refactor.py`)
- ✅ 7/7 tests passed
- Tests: Cooldown, Performance, Normalization, Prompt, Decision Model, URLs, Guardrails

### Acceptance Tests (`test_acceptance_criteria.py`)
- ✅ 3/3 acceptance criteria met
- All problem statement requirements validated

### Security Scan
- ✅ 0 security issues found (CodeQL scan)

## Files Modified

1. `agents/04_master_ai_agent/main.py`
   - Added structured fields to Decision model
   - Added `enforce_decision_consistency()` guardrail
   - Updated SYSTEM_PROMPT with structured process
   - Enhanced prompt context with constraints

2. `agents/orchestrator/main.py`
   - Enhanced payload with wallet info
   - Added position constraints
   - Calculated drawdown_pct

3. `dashboard/components/ai_reasoning.py`
   - Display blocked_by, direction_considered, setup_confirmations
   - Backward compatible rendering

4. `test_master_ai_refactor.py`
   - Added test for new fields
   - Added guardrail tests

5. `test_acceptance_criteria.py` (NEW)
   - Comprehensive acceptance criteria validation

## Impact

### For AI Decision Quality
- ✅ No more contradictory rationales
- ✅ Clear separation of confirmations vs. constraints
- ✅ Transparent blocking reasons
- ✅ Direction-consistent reasoning

### For Users/Operators
- ✅ Dashboard clearly shows why decisions were blocked
- ✅ Setup confirmations visible in UI
- ✅ Direction considered is explicit
- ✅ Better debugging of AI decisions

### For Developers
- ✅ Structured data easier to process
- ✅ Guardrails catch inconsistencies automatically
- ✅ Backward compatible with existing system
- ✅ Constants extracted for maintainability

## Conclusion

All problem statement requirements have been successfully implemented and validated. The system now produces coherent, deterministic AI decision rationales with clear separation between setup confirmations and blocking constraints.
