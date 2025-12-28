"""
FASE 2 Spread & Slippage Control Module

This module provides:
- Pre-trade spread checking (orderbook analysis)
- Post-fill slippage calculation
- Spread/slippage logging for telemetry
"""

from typing import Tuple, Optional, Dict, Any


def calculate_spread_from_orderbook(
    orderbook: dict,
    depth: int = 10
) -> Tuple[Optional[float], dict]:
    """
    Calculate bid-ask spread from orderbook.
    
    Args:
        orderbook: Orderbook data from exchange (format: {'bids': [[price, qty], ...], 'asks': [[price, qty], ...]})
        depth: Number of levels to consider (default 10)
    
    Returns:
        Tuple of (spread_pct, spread_info_dict)
        spread_pct is None if orderbook is invalid
    """
    spread_info = {}
    
    try:
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])
        
        if not bids or not asks:
            spread_info['error'] = 'Empty orderbook'
            return None, spread_info
        
        # Best bid/ask
        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        
        if best_bid <= 0 or best_ask <= 0:
            spread_info['error'] = 'Invalid bid/ask prices'
            return None, spread_info
        
        # Calculate mid price
        mid_price = (best_bid + best_ask) / 2.0
        
        # Calculate spread
        spread_abs = best_ask - best_bid
        spread_pct = spread_abs / mid_price
        
        spread_info['best_bid'] = best_bid
        spread_info['best_ask'] = best_ask
        spread_info['mid_price'] = mid_price
        spread_info['spread_abs'] = spread_abs
        spread_info['spread_pct'] = spread_pct
        
        # Additional orderbook metrics
        spread_info['bid_depth'] = len(bids)
        spread_info['ask_depth'] = len(asks)
        
        # Volume at best levels
        if bids and len(bids[0]) > 1:
            spread_info['best_bid_volume'] = float(bids[0][1])
        if asks and len(asks[0]) > 1:
            spread_info['best_ask_volume'] = float(asks[0][1])
        
        return spread_pct, spread_info
        
    except Exception as e:
        spread_info['error'] = f'Spread calculation failed: {str(e)}'
        return None, spread_info


def check_spread_acceptable(
    spread_pct: Optional[float],
    max_spread_pct: float = 0.0008
) -> Tuple[bool, str]:
    """
    Check if spread is acceptable for trade entry.
    
    Args:
        spread_pct: Spread as percentage (e.g., 0.0008 for 0.08%)
        max_spread_pct: Maximum acceptable spread
    
    Returns:
        Tuple of (is_acceptable, reason)
    """
    if spread_pct is None:
        return False, "Spread calculation failed (invalid orderbook)"
    
    if spread_pct > max_spread_pct:
        return False, f"Spread too wide: {spread_pct*100:.4f}% > {max_spread_pct*100:.4f}%"
    
    return True, "Spread acceptable"


def calculate_slippage(
    expected_price: float,
    fill_price: float,
    direction: str
) -> Tuple[float, dict]:
    """
    Calculate slippage after order fill.
    
    Slippage is the difference between expected price and actual fill price,
    expressed as a percentage of expected price.
    
    For LONG/BUY: Positive slippage = paid more than expected (worse)
    For SHORT/SELL: Positive slippage = received less than expected (worse)
    
    Args:
        expected_price: Expected execution price (e.g., mid price or limit price)
        fill_price: Actual fill price
        direction: 'long' (buy) or 'short' (sell)
    
    Returns:
        Tuple of (slippage_pct, slippage_info_dict)
    """
    slippage_info = {}
    
    if expected_price <= 0:
        slippage_info['error'] = 'Invalid expected price'
        return 0.0, slippage_info
    
    # Calculate slippage
    price_diff = fill_price - expected_price
    slippage_abs = abs(price_diff)
    slippage_pct = price_diff / expected_price
    
    slippage_info['expected_price'] = expected_price
    slippage_info['fill_price'] = fill_price
    slippage_info['price_diff'] = price_diff
    slippage_info['slippage_abs'] = slippage_abs
    slippage_info['slippage_pct'] = slippage_pct
    slippage_info['direction'] = direction
    
    # Determine if slippage is favorable or unfavorable
    if direction == 'long':
        # For long/buy: negative price_diff is favorable (bought cheaper)
        slippage_info['favorable'] = price_diff < 0
    else:  # short/sell
        # For short/sell: positive price_diff is favorable (sold higher)
        slippage_info['favorable'] = price_diff > 0
    
    return slippage_pct, slippage_info


def fetch_orderbook_safe(exchange, symbol: str, limit: int = 10) -> Optional[dict]:
    """
    Safely fetch orderbook from exchange with error handling.
    
    Args:
        exchange: CCXT exchange instance
        symbol: Trading symbol (e.g., "BTC/USDT:USDT")
        limit: Orderbook depth limit
    
    Returns:
        Orderbook dict or None if fetch fails
    """
    try:
        orderbook = exchange.fetch_order_book(symbol, limit=limit)
        return orderbook
    except Exception as e:
        print(f"⚠️ Failed to fetch orderbook for {symbol}: {e}")
        return None


def get_spread_and_check(
    exchange,
    symbol: str,
    max_spread_pct: float = 0.0008,
    orderbook_depth: int = 10
) -> Tuple[bool, Optional[float], dict]:
    """
    Convenience function to fetch orderbook, calculate spread, and check if acceptable.
    
    Args:
        exchange: CCXT exchange instance
        symbol: Trading symbol
        max_spread_pct: Maximum acceptable spread
        orderbook_depth: Orderbook depth to fetch
    
    Returns:
        Tuple of (is_acceptable, spread_pct, info_dict)
    """
    # Fetch orderbook
    orderbook = fetch_orderbook_safe(exchange, symbol, limit=orderbook_depth)
    
    if orderbook is None:
        return False, None, {'error': 'Failed to fetch orderbook'}
    
    # Calculate spread
    spread_pct, spread_info = calculate_spread_from_orderbook(orderbook, depth=orderbook_depth)
    
    # Check if acceptable
    is_acceptable, reason = check_spread_acceptable(spread_pct, max_spread_pct)
    
    info = {
        **spread_info,
        'is_acceptable': is_acceptable,
        'reason': reason,
        'max_spread_pct': max_spread_pct
    }
    
    return is_acceptable, spread_pct, info
