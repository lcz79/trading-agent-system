# PR: Improve Coherence and Determinism of AI Decision Rationales

## Summary

This PR resolves issues where the AI bot outputs contradictory rationales and mixes risk constraints with setup confirmations, leading to confusing and incorrect explanations.

## Problem Statement

**Before this PR:**
- Bot lists 5 confirmations for opening SHORT, but then says it will not open LONG and concludes HOLD ❌
- Risk constraints (drawdown, max positions, available margin) are mixed with setup confirmations in free-text ❌
- No way to understand why a valid setup was blocked ❌

**After this PR:**
- Decisions with strong confirmations return appropriate action or HOLD with explicit blocked_by reason ✅
- Setup confirmations are direction-specific and separated from risk factors ✅
- Dashboard clearly shows blocking reasons, direction considered, and confirmations ✅

## Changes Made

### 1. Master AI Agent (`agents/04_master_ai_agent/main.py`)

#### Added Structured Fields to Decision Model
```python
class Decision(BaseModel):
    # ... existing fields ...
    setup_confirmations: Optional[List[str]] = None  # Direction-specific confirmations
    blocked_by: Optional[List[BLOCKER_REASONS]] = None  # Explicit blocking reasons
    direction_considered: Optional[Literal["LONG", "SHORT", "NONE"]] = None  # Direction evaluated
```

#### Blocker Reasons Available
- `INSUFFICIENT_MARGIN` - Not enough wallet balance
- `MAX_POSITIONS` - At maximum position limit
- `COOLDOWN` - Position just closed on this symbol+direction
- `DRAWDOWN_GUARD` - System in excessive drawdown
- `PATTERN_LOSING` - Pattern has historical losses
- `CONFLICTING_SIGNALS` - Mixed/contradictory indicators
- `LOW_CONFIDENCE` - AI confidence below 50%

#### Implemented Guardrails Function
```python
def enforce_decision_consistency(decision_dict: dict) -> dict:
    """
    Post-processes AI decisions to enforce consistency:
    1. Infer direction_considered from action
    2. Validate action matches direction_considered
    3. Copy confirmations to setup_confirmations for backward compat
    4. Infer blocked_by for HOLD with low confidence
    5. Force HOLD when blocked_by is present
    6. Warn about contradictory rationales
    """
```

#### Updated System Prompt
- Enforces structured decision-making process
- Requires direction-consistent confirmations
- Separates setup confirmations from risk factors
- Mandates blocked_by when constraints prevent action

### 2. Orchestrator (`agents/orchestrator/main.py`)

Enhanced payload sent to Master AI:
```python
enhanced_global_data = {
    "portfolio": portfolio,
    "already_open": active_symbols,
    "max_positions": MAX_POSITIONS,  # NEW
    "positions_open_count": num_positions,  # NEW
    "wallet": {  # NEW
        "equity": portfolio.get('equity', 0),
        "available": portfolio.get('available', 0),
        "available_for_new_trades": portfolio.get('available', 0) * 0.95
    },
    "drawdown_pct": drawdown_pct  # NEW (if calculated)
}
```

### 3. Dashboard (`dashboard/components/ai_reasoning.py`)

Added display for new fields:
- `blocked_by` - Red badge showing blocking reasons
- `direction_considered` - Colored badge (green=LONG, red=SHORT)
- `setup_confirmations` - Expandable list of direction-specific confirmations

**Backward Compatible:** Old decisions without new fields still render correctly.

### 4. Tests

#### Updated `test_master_ai_refactor.py`
- Added test for new Decision model fields
- Added comprehensive guardrails testing (7 test cases)

#### New `test_acceptance_criteria.py`
Validates all problem statement requirements:
1. Decision with 5 SHORT confirmations returns OPEN_SHORT or HOLD with blocked_by
2. No mismatched text like 'BTC long' blocking OPEN_SHORT
3. Backward compatibility with old decision format

### 5. Documentation

- **AI_DECISION_IMPROVEMENTS.md** - Technical summary with before/after examples
- **VISUAL_EXAMPLES.md** - Visual comparisons and data flow diagram
- **This README** - Comprehensive PR documentation

## Examples

### Example 1: Blocked Setup (NEW Behavior)

**AI Output:**
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
  "rationale": "Setup SHORT valido con 5 conferme bearish. Bloccato da margine insufficiente."
}
```

**Dashboard Display:**
```
⏸️ HOLD on BTCUSDT
🎯 Direction Considered: SHORT
🚫 Blocked By: INSUFFICIENT_MARGIN

💡 Rationale: Setup SHORT valido con 5 conferme bearish. Bloccato da margine insufficiente.

✅ Setup Confirmations:
  • RSI > 70 (ipercomprato)
  • Trend bearish su 1h e 4h
  • Resistenza Fibonacci rifiutata
  • News sentiment negativo
  • Forecast prevede calo
```

### Example 2: Valid Opening (NEW Behavior)

**AI Output:**
```json
{
  "action": "OPEN_SHORT",
  "direction_considered": "SHORT",
  "setup_confirmations": ["Trend bearish 1h/4h", "RSI > 70", "Resistenza rifiutata"],
  "blocked_by": [],
  "rationale": "Setup SHORT confermato con alta confidenza. Apertura con leverage moderato.",
  "leverage": 5.0,
  "size_pct": 0.15
}
```

**Dashboard Display:**
```
🔴 OPEN SHORT on BTCUSDT
🎯 Direction Considered: SHORT
🚫 Blocked By: (none)

💡 Rationale: Setup SHORT confermato con alta confidenza. Apertura con leverage moderato.

✅ Setup Confirmations:
  • Trend bearish 1h/4h
  • RSI > 70
  • Resistenza rifiutata

⚡ Leverage: 5x | 📈 Size: 15%
```

## Test Results

```
✅ Unit Tests:        7/7 passed
✅ Acceptance Tests:  3/3 passed
✅ Security Scan:     0 issues found
✅ Code Review:       All feedback addressed
```

### Running Tests

```bash
# Run unit tests
python test_master_ai_refactor.py

# Run acceptance criteria tests
python test_acceptance_criteria.py
```

## Acceptance Criteria

All acceptance criteria from the problem statement are met:

✅ **Criterion 1:** A decision that lists 5 confirmations for SHORT will either return OPEN_SHORT or, if blocked, return HOLD with `blocked_by` explaining why (e.g., INSUFFICIENT_MARGIN), and rationale text aligned.

✅ **Criterion 2:** No more mismatched text like 'pattern BTC long' as reason to block an OPEN_SHORT setup. Risk factors are now separated from setup confirmations.

✅ **Criterion 3:** Backward compatible: dashboard still renders old decisions without errors. Old decisions are automatically enhanced by guardrails.

## Migration & Compatibility

### For Existing Decisions
- Old format decisions automatically enhanced by guardrails
- Missing fields are inferred when possible
- No breaking changes to existing code

### For Dashboard
- New fields displayed when present
- Gracefully handles missing fields
- Backward compatible with pre-refactor decisions

### For Developers
- New fields are optional in Decision model
- Guardrails ensure consistency automatically
- Constants extracted for easy configuration

## Deployment Notes

1. No database migrations required (JSON file-based storage)
2. No breaking changes to API endpoints
3. Dashboard updates are backward compatible
4. Tests pass on all components

## Files Changed

| File | Changes | Description |
|------|---------|-------------|
| `agents/04_master_ai_agent/main.py` | +187, -56 | Core logic: Decision model, guardrails, prompt |
| `agents/orchestrator/main.py` | +23, -1 | Enhanced payload with constraints |
| `dashboard/components/ai_reasoning.py` | +39 | Display new fields |
| `test_master_ai_refactor.py` | +156, -8 | Updated tests for new fields |
| `test_acceptance_criteria.py` | NEW: 256 lines | Acceptance criteria validation |
| `AI_DECISION_IMPROVEMENTS.md` | NEW: 159 lines | Technical documentation |
| `VISUAL_EXAMPLES.md` | NEW: 178 lines | Visual examples |

**Total:** +764 insertions, -56 deletions across 7 files

## Security

✅ CodeQL scan: 0 security issues found

## Related Issues

Resolves issues with contradictory AI rationales as described in problem statement.

## Review Checklist

- [x] All tests pass (10/10)
- [x] Code review feedback addressed
- [x] Security scan passed (0 issues)
- [x] Backward compatibility verified
- [x] Documentation complete
- [x] Acceptance criteria validated
- [x] Examples provided
- [x] Ready for merge

---

**Author:** GitHub Copilot Agent
**Co-authored-by:** lcz79 <235707880+lcz79@users.noreply.github.com>
