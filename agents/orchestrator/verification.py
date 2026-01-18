"""
Verification and Safety Gates Module

Implements deterministic safety checks before executing trading decisions:

1. HARD BLOCK checks (prevent execution):
   - Low confluence (< 40)
   - Invalid LIMIT entry parameters
   - Invalid risk parameters (size/leverage/tp/sl bounds)
   - Strong opposition from major timeframes

2. SOFT DEGRADE behavior (modify parameters):
   - Medium confluence (40-60) → reduce size
   - High volatility → reduce size
   - Regime mismatch → prefer LIMIT in RANGE
   - Clamp TTL to safe ranges

All decisions are deterministic, logged, and return clear reasons.
"""

from typing import Dict, Optional, Tuple, Literal, List
from datetime import datetime

# Hard block thresholds
MIN_CONFLUENCE_THRESHOLD = 40
MIN_LIMIT_TTL_SEC = 60
MAX_LIMIT_TTL_SEC = 600

# Risk parameter bounds
MIN_LEVERAGE = 1.0
MAX_LEVERAGE = 20.0
MIN_SIZE_PCT = 0.01
MAX_SIZE_PCT = 0.30
MIN_TP_PCT = 0.005  # 0.5%
MAX_TP_PCT = 0.10   # 10%
MIN_SL_PCT = 0.005  # 0.5%
MAX_SL_PCT = 0.05   # 5%

# Degrade thresholds
MEDIUM_CONFLUENCE_THRESHOLD = 60
DEGRADE_SIZE_MULTIPLIER = 0.6  # Reduce size by 40%


class VerificationResult:
    """Result of verification check."""
    
    def __init__(
        self,
        allowed: bool,
        action: Literal["BLOCK", "DEGRADE", "ALLOW"],
        reasons: List[str],
        modified_params: Optional[Dict[str, any]] = None
    ):
        self.allowed = allowed
        self.action = action
        self.reasons = reasons
        self.modified_params = modified_params or {}
        self.timestamp = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, any]:
        """Convert to dictionary for logging."""
        return {
            "allowed": self.allowed,
            "action": self.action,
            "reasons": self.reasons,
            "modified_params": self.modified_params,
            "timestamp": self.timestamp
        }


def verify_confluence(
    direction: Literal["LONG", "SHORT"],
    confluence_score: int
) -> Tuple[bool, Optional[str]]:
    """
    Verify confluence score meets minimum threshold.
    
    Args:
        direction: Trade direction
        confluence_score: Confluence score (0-100)
    
    Returns:
        Tuple of (passes, reason)
    """
    if confluence_score < MIN_CONFLUENCE_THRESHOLD:
        return False, f"Confluence too low: {confluence_score} < {MIN_CONFLUENCE_THRESHOLD}"
    return True, None


def verify_limit_entry_params(
    entry_type: str,
    entry_price: Optional[float],
    entry_ttl_sec: Optional[int],
    current_price: float
) -> Tuple[bool, Optional[str]]:
    """
    Verify LIMIT entry parameters are valid.
    
    Args:
        entry_type: Entry type ("MARKET" or "LIMIT")
        entry_price: Limit entry price
        entry_ttl_sec: Time to live in seconds
        current_price: Current market price
    
    Returns:
        Tuple of (passes, reason)
    """
    if entry_type != "LIMIT":
        return True, None
    
    # Must have entry price
    if entry_price is None or entry_price <= 0:
        return False, f"LIMIT entry missing valid entry_price: {entry_price}"
    
    # Must have TTL in valid range
    if entry_ttl_sec is None:
        return False, "LIMIT entry missing entry_ttl_sec"
    
    if entry_ttl_sec < MIN_LIMIT_TTL_SEC:
        return False, f"LIMIT entry TTL too short: {entry_ttl_sec}s < {MIN_LIMIT_TTL_SEC}s"
    
    if entry_ttl_sec > MAX_LIMIT_TTL_SEC:
        return False, f"LIMIT entry TTL too long: {entry_ttl_sec}s > {MAX_LIMIT_TTL_SEC}s"
    
    # Entry price should be reasonable (within 2% of current price)
    if current_price and current_price > 0:
        price_diff_pct = abs(entry_price - current_price) / current_price
        if price_diff_pct > 0.02:
            return False, f"LIMIT entry price too far from market: {price_diff_pct*100:.2f}% > 2%"
    
    return True, None


def verify_risk_params(
    leverage: float,
    size_pct: float,
    tp_pct: Optional[float] = None,
    sl_pct: Optional[float] = None
) -> Tuple[bool, Optional[str]]:
    """
    Verify risk parameters are within safe bounds.
    
    Args:
        leverage: Position leverage
        size_pct: Position size as percentage of equity
        tp_pct: Take profit percentage (optional)
        sl_pct: Stop loss percentage (optional)
    
    Returns:
        Tuple of (passes, reason)
    """
    # Check leverage bounds
    if leverage < MIN_LEVERAGE:
        return False, f"Leverage too low: {leverage} < {MIN_LEVERAGE}"
    if leverage > MAX_LEVERAGE:
        return False, f"Leverage too high: {leverage} > {MAX_LEVERAGE}"
    
    # Check size bounds
    if size_pct < MIN_SIZE_PCT:
        return False, f"Size too small: {size_pct:.3f} < {MIN_SIZE_PCT}"
    if size_pct > MAX_SIZE_PCT:
        return False, f"Size too large: {size_pct:.3f} > {MAX_SIZE_PCT}"
    
    # Check TP bounds if provided
    if tp_pct is not None:
        if tp_pct < MIN_TP_PCT:
            return False, f"TP too tight: {tp_pct:.4f} < {MIN_TP_PCT}"
        if tp_pct > MAX_TP_PCT:
            return False, f"TP too wide: {tp_pct:.4f} > {MAX_TP_PCT}"
    
    # Check SL bounds if provided
    if sl_pct is not None:
        if sl_pct < MIN_SL_PCT:
            return False, f"SL too tight: {sl_pct:.4f} < {MIN_SL_PCT}"
        if sl_pct > MAX_SL_PCT:
            return False, f"SL too wide: {sl_pct:.4f} > {MAX_SL_PCT}"
    
    return True, None


def verify_timeframe_opposition(
    direction: Literal["LONG", "SHORT"],
    timeframes: Dict[str, Dict]
) -> Tuple[bool, Optional[str]]:
    """
    Check for strong opposition from 1h timeframe.
    
    Args:
        direction: Intended trade direction
        timeframes: Timeframe data dictionary
    
    Returns:
        Tuple of (passes, reason)
    """
    tf_1h = timeframes.get("1h", {})
    
    if not tf_1h:
        return True, None
    
    trend_1h = (tf_1h.get("trend") or "").lower()
    return_1h = tf_1h.get("return_1h", 0)
    
    # Check for strong opposition
    if direction == "LONG":
        # Block if 1h is strongly bearish
        if "bear" in trend_1h and return_1h < -0.5:
            return False, f"Strong 1h opposition: bearish trend with {return_1h:.2f}% return"
    else:  # SHORT
        # Block if 1h is strongly bullish
        if "bull" in trend_1h and return_1h > 0.5:
            return False, f"Strong 1h opposition: bullish trend with {return_1h:.2f}% return"
    
    return True, None


def apply_degrade_logic(
    decision: Dict[str, any],
    confluence_score: int,
    volatility_bucket: str,
    regime: str,
    timeframes: Dict[str, Dict]
) -> Tuple[Dict[str, any], List[str]]:
    """
    Apply soft degrade logic to modify decision parameters.
    
    Args:
        decision: Trading decision dictionary
        confluence_score: Confluence score (0-100)
        volatility_bucket: Volatility classification
        regime: Market regime
        timeframes: Timeframe data
    
    Returns:
        Tuple of (modified_decision, degrade_reasons)
    """
    modified = decision.copy()
    reasons = []
    
    # Degrade 1: Medium confluence (40-60)
    if MIN_CONFLUENCE_THRESHOLD <= confluence_score < MEDIUM_CONFLUENCE_THRESHOLD:
        original_size = modified.get("size_pct", 0.15)
        modified["size_pct"] = original_size * DEGRADE_SIZE_MULTIPLIER
        reasons.append(
            f"Reduced size by {(1-DEGRADE_SIZE_MULTIPLIER)*100:.0f}% due to medium confluence "
            f"({confluence_score}): {original_size:.3f} → {modified['size_pct']:.3f}"
        )
    
    # Degrade 2: High volatility
    if volatility_bucket in ["HIGH", "EXTREME"]:
        original_size = modified.get("size_pct", 0.15)
        modified["size_pct"] = original_size * DEGRADE_SIZE_MULTIPLIER
        reasons.append(
            f"Reduced size by {(1-DEGRADE_SIZE_MULTIPLIER)*100:.0f}% due to {volatility_bucket} volatility: "
            f"{original_size:.3f} → {modified['size_pct']:.3f}"
        )
    
    # Degrade 3: Prefer LIMIT in RANGE regime if entry_type is MARKET
    if regime == "RANGE" and modified.get("entry_type") == "MARKET":
        # Don't force LIMIT as it requires price calculation
        # Just flag it for consideration
        reasons.append(
            f"Suggestion: Consider LIMIT entry in RANGE regime for better entry price"
        )
    
    # Degrade 4: Clamp TTL to safe range if provided
    entry_ttl_sec = modified.get("entry_ttl_sec")
    if entry_ttl_sec is not None:
        original_ttl = entry_ttl_sec
        clamped_ttl = max(MIN_LIMIT_TTL_SEC, min(MAX_LIMIT_TTL_SEC, entry_ttl_sec))
        if clamped_ttl != original_ttl:
            modified["entry_ttl_sec"] = clamped_ttl
            reasons.append(
                f"Clamped TTL to safe range: {original_ttl}s → {clamped_ttl}s"
            )
    
    # Degrade 5: Reduce leverage in high volatility
    if volatility_bucket == "EXTREME":
        original_leverage = modified.get("leverage", 5.0)
        modified["leverage"] = max(MIN_LEVERAGE, original_leverage * 0.8)
        reasons.append(
            f"Reduced leverage due to EXTREME volatility: "
            f"{original_leverage:.1f}x → {modified['leverage']:.1f}x"
        )
    
    return modified, reasons


def verify_decision(
    decision: Dict[str, any],
    tech_data: Dict[str, any],
    enhanced_data: Dict[str, any]
) -> VerificationResult:
    """
    Main verification function - checks all safety gates.
    
    Args:
        decision: Trading decision from AI agent
        tech_data: Technical analysis data
        enhanced_data: Enhanced preprocessing data (regime, confluence, etc.)
    
    Returns:
        VerificationResult with action and reasons
    """
    action_type = decision.get("action", "HOLD")
    
    # Only verify OPEN actions
    if action_type not in ["OPEN_LONG", "OPEN_SHORT"]:
        return VerificationResult(
            allowed=True,
            action="ALLOW",
            reasons=["Non-OPEN action, no verification needed"]
        )
    
    direction = "LONG" if action_type == "OPEN_LONG" else "SHORT"
    symbol = decision.get("symbol", "UNKNOWN")
    
    block_reasons = []
    
    # Extract enhanced data
    confluence_score = enhanced_data.get("confluence_score", 0)
    volatility_bucket = enhanced_data.get("volatility_bucket", "LOW")
    regime = enhanced_data.get("regime", "UNKNOWN")
    timeframes = tech_data.get("timeframes", {})
    
    # HARD CHECK 1: Confluence
    passes, reason = verify_confluence(direction, confluence_score)
    if not passes:
        block_reasons.append(reason)
    
    # HARD CHECK 2: LIMIT entry parameters
    entry_type = decision.get("entry_type", "MARKET")
    entry_price = decision.get("entry_price")
    entry_ttl_sec = decision.get("entry_ttl_sec") or decision.get("entry_expires_sec")
    current_price = tech_data.get("timeframes", {}).get("15m", {}).get("price", 0)
    
    passes, reason = verify_limit_entry_params(entry_type, entry_price, entry_ttl_sec, current_price)
    if not passes:
        block_reasons.append(reason)
    
    # HARD CHECK 3: Risk parameters
    leverage = decision.get("leverage", 5.0)
    size_pct = decision.get("size_pct", 0.15)
    tp_pct = decision.get("tp_pct")
    sl_pct = decision.get("sl_pct")
    
    passes, reason = verify_risk_params(leverage, size_pct, tp_pct, sl_pct)
    if not passes:
        block_reasons.append(reason)
    
    # HARD CHECK 4: Strong 1h opposition
    passes, reason = verify_timeframe_opposition(direction, timeframes)
    if not passes:
        block_reasons.append(reason)
    
    # If any hard blocks, return BLOCK result
    if block_reasons:
        return VerificationResult(
            allowed=False,
            action="BLOCK",
            reasons=block_reasons
        )
    
    # No hard blocks - check for soft degrade conditions
    modified_decision, degrade_reasons = apply_degrade_logic(
        decision, confluence_score, volatility_bucket, regime, timeframes
    )
    
    if degrade_reasons:
        return VerificationResult(
            allowed=True,
            action="DEGRADE",
            reasons=degrade_reasons,
            modified_params=modified_decision
        )
    
    # All checks passed, no modifications needed
    return VerificationResult(
        allowed=True,
        action="ALLOW",
        reasons=["All safety checks passed"]
    )
