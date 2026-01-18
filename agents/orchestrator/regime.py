"""
Market Regime Detection Module

Implements deterministic regime classification with hysteresis to avoid flapping:
- TREND: Strong directional movement (ADX > threshold)
- RANGE: Sideways consolidation (ADX < threshold, low volatility)
- TRANSITION: Mixed signals or intermediate state

Uses ADX from 15m timeframe with minimum duration hysteresis.
"""

from datetime import datetime, timedelta
from typing import Dict, Tuple, Literal, Optional

# Regime state cache: {symbol: (regime, timestamp)}
_regime_cache: Dict[str, Tuple[str, datetime]] = {}

# Hysteresis configuration
MIN_REGIME_DURATION_SEC = 300  # 5 minutes minimum before regime can change
ADX_TREND_THRESHOLD = 25.0
ADX_RANGE_THRESHOLD = 20.0


def calculate_volatility_bucket(atr: float, price: float) -> Literal["LOW", "MEDIUM", "HIGH", "EXTREME"]:
    """
    Calculate volatility bucket based on ATR as percentage of price.
    
    Args:
        atr: Average True Range value
        price: Current price
    
    Returns:
        Volatility bucket: LOW, MEDIUM, HIGH, or EXTREME
    """
    if price <= 0 or atr < 0:
        return "LOW"
    
    atr_pct = (atr / price) * 100
    
    if atr_pct < 0.5:
        return "LOW"
    elif atr_pct < 1.5:
        return "MEDIUM"
    elif atr_pct < 3.0:
        return "HIGH"
    else:
        return "EXTREME"


def detect_regime_with_hysteresis(
    symbol: str,
    adx: float,
    atr: float,
    price: float,
    trend: Optional[str] = None,
    ema_20: Optional[float] = None,
    ema_50: Optional[float] = None,
    force_recalc: bool = False
) -> Tuple[Literal["TREND", "RANGE", "TRANSITION"], Dict[str, any]]:
    """
    Detect market regime with hysteresis to prevent flapping.
    
    Uses ADX as primary signal with minimum duration requirement.
    Once a regime is established, it requires MIN_REGIME_DURATION_SEC
    to elapse before switching to a different regime.
    
    Args:
        symbol: Trading symbol
        adx: ADX indicator value (15m timeframe recommended)
        atr: Average True Range
        price: Current price
        trend: Optional trend direction from technical analysis
        ema_20: Optional EMA20 for additional context
        ema_50: Optional EMA50 for additional context
        force_recalc: Force recalculation ignoring hysteresis
    
    Returns:
        Tuple of (regime, metadata_dict)
        - regime: "TREND", "RANGE", or "TRANSITION"
        - metadata: Dictionary with regime details and confidence
    """
    now = datetime.now()
    
    # Calculate current regime based on indicators
    if adx >= ADX_TREND_THRESHOLD:
        current_regime = "TREND"
        confidence = min(100, int((adx / ADX_TREND_THRESHOLD) * 60))
    elif adx <= ADX_RANGE_THRESHOLD:
        current_regime = "RANGE"
        # Lower ADX = higher range confidence
        confidence = min(100, int((1.0 - adx / ADX_RANGE_THRESHOLD) * 60 + 40))
    else:
        current_regime = "TRANSITION"
        confidence = 50
    
    # Calculate volatility bucket for additional context
    volatility_bucket = calculate_volatility_bucket(atr, price)
    
    # Build metadata
    metadata = {
        "adx": round(adx, 2),
        "atr": round(atr, 4) if atr is not None else None,
        "price": round(price, 2) if price is not None else None,
        "atr_pct": round((atr / price * 100), 4) if (price and price > 0 and atr) else None,
        "volatility_bucket": volatility_bucket,
        "confidence": confidence,
        "trend_direction": trend,
        "timestamp": now.isoformat(),
    }
    
    # Add EMA information if available
    if ema_20 is not None and ema_50 is not None and price is not None:
        ema_alignment = "bullish" if ema_20 > ema_50 else "bearish"
        price_vs_ema20 = "above" if price > ema_20 else "below"
        metadata["ema_alignment"] = ema_alignment
        metadata["price_vs_ema20"] = price_vs_ema20
    
    # Check cache for hysteresis
    if not force_recalc and symbol in _regime_cache:
        cached_regime, cached_time = _regime_cache[symbol]
        elapsed = (now - cached_time).total_seconds()
        
        # If regime hasn't changed or minimum duration not elapsed, keep cached
        if current_regime == cached_regime:
            # Update timestamp but keep regime
            _regime_cache[symbol] = (cached_regime, now)
            metadata["from_cache"] = False
            metadata["regime_age_sec"] = elapsed
            return cached_regime, metadata
        elif elapsed < MIN_REGIME_DURATION_SEC:
            # Too soon to change, keep old regime
            metadata["from_cache"] = True
            metadata["regime_age_sec"] = elapsed
            metadata["blocked_switch"] = f"{cached_regime} -> {current_regime}"
            metadata["min_duration_sec"] = MIN_REGIME_DURATION_SEC
            return cached_regime, metadata
    
    # Update cache with new regime
    _regime_cache[symbol] = (current_regime, now)
    metadata["from_cache"] = False
    metadata["regime_age_sec"] = 0
    
    return current_regime, metadata


def clear_regime_cache(symbol: Optional[str] = None):
    """
    Clear regime cache for a symbol or all symbols.
    
    Args:
        symbol: Symbol to clear, or None to clear all
    """
    global _regime_cache
    if symbol is None:
        _regime_cache.clear()
    elif symbol in _regime_cache:
        del _regime_cache[symbol]


def get_regime_summary() -> Dict[str, any]:
    """
    Get summary of all cached regimes.
    
    Returns:
        Dictionary with cache statistics
    """
    now = datetime.now()
    summary = {
        "total_cached": len(_regime_cache),
        "symbols": []
    }
    
    for symbol, (regime, timestamp) in _regime_cache.items():
        age_sec = (now - timestamp).total_seconds()
        summary["symbols"].append({
            "symbol": symbol,
            "regime": regime,
            "age_sec": int(age_sec)
        })
    
    return summary
