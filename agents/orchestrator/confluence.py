"""
Timeframe Confluence Scoring Module

Computes a deterministic confluence score (0-100) based on:
- Trend alignment across multiple timeframes (15m, 1h, 4h, 1d)
- Return/momentum alignment across timeframes
- Weighted scoring with major TF conflict penalties

Higher scores indicate stronger multi-timeframe agreement.
Lower scores indicate conflicting signals across timeframes.
"""

from typing import Dict, Optional, Literal

# Timeframe weights (must sum to 1.0)
TF_WEIGHTS = {
    "15m": 0.4,   # Primary scalping timeframe
    "1h": 0.3,    # Confirmation timeframe
    "4h": 0.2,    # Macro trend
    "1d": 0.1     # Context
}

# Penalties
MAJOR_TF_CONFLICT_PENALTY = 25  # Penalty when 1h or 4h opposes direction


def _normalize_trend(trend: Optional[str]) -> Literal["bullish", "bearish", "neutral"]:
    """Normalize trend string to standard values."""
    if not trend:
        return "neutral"
    t = str(trend).lower().strip()
    if "bull" in t or "up" in t:
        return "bullish"
    elif "bear" in t or "down" in t:
        return "bearish"
    else:
        return "neutral"


def _get_return_sign(return_val: Optional[float], threshold: float = 0.1) -> Literal["positive", "negative", "neutral"]:
    """
    Get sign of return with threshold for noise filtering.
    
    Args:
        return_val: Return percentage
        threshold: Minimum absolute value to consider non-neutral (default 0.1%)
    """
    if return_val is None:
        return "neutral"
    if return_val > threshold:
        return "positive"
    elif return_val < -threshold:
        return "negative"
    else:
        return "neutral"


def calculate_confluence_score(
    direction: Literal["LONG", "SHORT"],
    timeframes: Dict[str, Dict],
    apply_penalties: bool = True
) -> tuple[int, Dict[str, any]]:
    """
    Calculate multi-timeframe confluence score for a given direction.
    
    Args:
        direction: Trade direction ("LONG" or "SHORT")
        timeframes: Dictionary of timeframe data from technical analyzer
                   Expected keys: "15m", "1h", "4h", "1d"
                   Each contains: trend, return_15m/1h/4h/1d, etc.
        apply_penalties: Whether to apply major TF conflict penalties
    
    Returns:
        Tuple of (score, breakdown_dict)
        - score: 0-100, higher means stronger confluence
        - breakdown: Detailed scoring breakdown
    """
    score = 0
    breakdown = {
        "direction": direction,
        "trend_alignment": {},
        "return_alignment": {},
        "weighted_scores": {},
        "penalties": [],
        "total_before_penalties": 0,
        "total_after_penalties": 0
    }
    
    # Determine expected trend and return sign for this direction
    expected_trend = "bullish" if direction == "LONG" else "bearish"
    expected_return = "positive" if direction == "LONG" else "negative"
    
    # Calculate trend alignment for each timeframe
    for tf, weight in TF_WEIGHTS.items():
        tf_data = timeframes.get(tf, {})
        
        # Get trend
        trend = _normalize_trend(tf_data.get("trend"))
        
        # Get return (try multiple field names for backward compatibility)
        return_field = f"return_{tf}" if tf != "15m" else "return_15m"
        return_val = tf_data.get(return_field)
        if return_val is None:
            # Try alternative fields
            return_val = tf_data.get("return")
        return_sign = _get_return_sign(return_val)
        
        # Score trend alignment (0-100 points per TF)
        trend_score = 0
        if trend == expected_trend:
            trend_score = 100
        elif trend == "neutral":
            trend_score = 50
        # else: opposite trend = 0 points
        
        # Score return alignment (0-100 points per TF)
        return_score = 0
        if return_sign == expected_return:
            return_score = 100
        elif return_sign == "neutral":
            return_score = 50
        # else: opposite return = 0 points
        
        # Combined score for this TF (0-100): average of trend and return
        tf_score = (trend_score + return_score) / 2.0
        
        # Weight by timeframe importance
        weighted_score = tf_score * weight  # weight is 0-1, so result is 0-weight*100
        score += weighted_score
        
        # Store breakdown
        breakdown["trend_alignment"][tf] = {
            "trend": trend,
            "expected": expected_trend,
            "match": trend == expected_trend,
            "score": trend_score
        }
        breakdown["return_alignment"][tf] = {
            "return": return_val,
            "sign": return_sign,
            "expected": expected_return,
            "match": return_sign == expected_return,
            "score": return_score
        }
        breakdown["weighted_scores"][tf] = {
            "raw_score": tf_score,
            "weight": weight,
            "weighted_score": weighted_score
        }
    
    breakdown["total_before_penalties"] = int(round(score))
    
    # Apply major TF conflict penalties
    if apply_penalties:
        # Check 1h opposition
        tf_1h = timeframes.get("1h", {})
        trend_1h = _normalize_trend(tf_1h.get("trend"))
        return_1h = _get_return_sign(tf_1h.get("return_1h"))
        
        opposite_trend = "bearish" if direction == "LONG" else "bullish"
        opposite_return = "negative" if direction == "LONG" else "positive"
        
        if trend_1h == opposite_trend and return_1h == opposite_return:
            score -= MAJOR_TF_CONFLICT_PENALTY
            breakdown["penalties"].append({
                "type": "1h_opposition",
                "penalty": MAJOR_TF_CONFLICT_PENALTY,
                "reason": f"1h shows {opposite_trend} trend with {opposite_return} return"
            })
        
        # Check 4h opposition
        tf_4h = timeframes.get("4h", {})
        trend_4h = _normalize_trend(tf_4h.get("trend"))
        return_4h = _get_return_sign(tf_4h.get("return_4h"))
        
        if trend_4h == opposite_trend and return_4h == opposite_return:
            score -= MAJOR_TF_CONFLICT_PENALTY
            breakdown["penalties"].append({
                "type": "4h_opposition",
                "penalty": MAJOR_TF_CONFLICT_PENALTY,
                "reason": f"4h shows {opposite_trend} trend with {opposite_return} return"
            })
    
    # Clamp to 0-100 range
    final_score = max(0, min(100, int(round(score))))
    breakdown["total_after_penalties"] = final_score
    
    return final_score, breakdown


def calculate_tf_aligned(timeframes: Dict[str, Dict]) -> bool:
    """
    Calculate simple boolean TF alignment (backward compatible with existing tech analyzer).
    
    Returns True if major timeframes (15m, 1h, 4h) are aligned in trend.
    
    Args:
        timeframes: Dictionary of timeframe data
    
    Returns:
        Boolean indicating if timeframes are aligned
    """
    trends = []
    for tf in ["15m", "1h", "4h"]:
        tf_data = timeframes.get(tf, {})
        trend = _normalize_trend(tf_data.get("trend"))
        if trend != "neutral":
            trends.append(trend)
    
    if not trends:
        return False
    
    # Check if all non-neutral trends agree
    return len(set(trends)) == 1


def get_confluence_summary(
    timeframes: Dict[str, Dict]
) -> Dict[str, any]:
    """
    Get confluence summary for both directions.
    
    Args:
        timeframes: Dictionary of timeframe data
    
    Returns:
        Dictionary with scores and recommendations for both LONG and SHORT
    """
    long_score, long_breakdown = calculate_confluence_score("LONG", timeframes)
    short_score, short_breakdown = calculate_confluence_score("SHORT", timeframes)
    
    # Determine recommendation
    if long_score >= 70 and short_score < 40:
        recommendation = "LONG"
        confidence = "HIGH"
    elif short_score >= 70 and long_score < 40:
        recommendation = "SHORT"
        confidence = "HIGH"
    elif long_score >= 60:
        recommendation = "LONG"
        confidence = "MEDIUM"
    elif short_score >= 60:
        recommendation = "SHORT"
        confidence = "MEDIUM"
    else:
        recommendation = "NEUTRAL"
        confidence = "LOW"
    
    return {
        "long_score": long_score,
        "short_score": short_score,
        "recommendation": recommendation,
        "confidence": confidence,
        "tf_aligned": calculate_tf_aligned(timeframes),
        "long_breakdown": long_breakdown,
        "short_breakdown": short_breakdown
    }
