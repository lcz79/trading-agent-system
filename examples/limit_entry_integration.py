#!/usr/bin/env python3
"""
Integration example: Using LIMIT entry orders from orchestrator/master AI.

This example demonstrates how to integrate LIMIT entry order support
into the orchestrator or master AI agent.
"""

import requests
import json
import time
from typing import Optional

# Position Manager URL
POSITION_MANAGER_URL = "http://07_position_manager:8000"


def open_market_position(symbol: str, side: str, leverage: float, size_pct: float, 
                         sl_pct: float, **kwargs) -> dict:
    """
    Open a MARKET position (backward compatible - default behavior).
    
    Args:
        symbol: Trading symbol (e.g., "BTCUSDT")
        side: "long"/"buy" or "short"/"sell"
        leverage: Leverage multiplier (e.g., 5.0)
        size_pct: Position size as % of available balance (e.g., 0.15 = 15%)
        sl_pct: Stop-loss percentage (e.g., 0.02 = 2%)
        **kwargs: Additional parameters (time_in_trade_limit_sec, cooldown_sec, etc.)
    
    Returns:
        Response dict with status, order_id, intent_id
    """
    payload = {
        "symbol": symbol,
        "side": side,
        "leverage": leverage,
        "size_pct": size_pct,
        "sl_pct": sl_pct,
        **kwargs
    }
    
    response = requests.post(f"{POSITION_MANAGER_URL}/open_position", json=payload, timeout=30)
    return response.json()


def open_limit_position(symbol: str, side: str, entry_price: float, 
                       leverage: float, size_pct: float, sl_pct: float,
                       entry_ttl_sec: int = 3600, **kwargs) -> dict:
    """
    Open a LIMIT position with specified entry price.
    
    Args:
        symbol: Trading symbol (e.g., "BTCUSDT")
        side: "long"/"buy" or "short"/"sell"
        entry_price: Desired entry price for LIMIT order
        leverage: Leverage multiplier (e.g., 5.0)
        size_pct: Position size as % of available balance (e.g., 0.15 = 15%)
        sl_pct: Stop-loss percentage (e.g., 0.02 = 2%)
        entry_ttl_sec: Time-to-live in seconds (default 3600 = 1 hour)
        **kwargs: Additional parameters (intent_id, time_in_trade_limit_sec, etc.)
    
    Returns:
        Response dict with status, order_id, intent_id, expires_at
    """
    payload = {
        "symbol": symbol,
        "side": side,
        "entry_type": "LIMIT",
        "entry_price": entry_price,
        "entry_ttl_sec": entry_ttl_sec,
        "leverage": leverage,
        "size_pct": size_pct,
        "sl_pct": sl_pct,
        **kwargs
    }
    
    response = requests.post(f"{POSITION_MANAGER_URL}/open_position", json=payload, timeout=30)
    return response.json()


# ============================================================================
# USAGE EXAMPLES
# ============================================================================

def example_market_entry():
    """Example: Open MARKET position (backward compatible)"""
    print("=" * 60)
    print("Example: MARKET Entry (Backward Compatible)")
    print("=" * 60)
    
    result = open_market_position(
        symbol="BTCUSDT",
        side="long",
        leverage=5.0,
        size_pct=0.15,
        sl_pct=0.02,
        time_in_trade_limit_sec=7200,  # 2 hours max
        cooldown_sec=300
    )
    
    print(f"Status: {result.get('status')}")
    print(f"Order ID: {result.get('exchange_order_id')}")
    print(f"Intent ID: {result.get('intent_id')}")
    print()


def example_limit_entry_simple():
    """Example: Open LIMIT position with basic parameters"""
    print("=" * 60)
    print("Example: LIMIT Entry (Simple)")
    print("=" * 60)
    
    current_price = 50000.0  # BTC current price
    entry_price = current_price * 0.98  # Enter at 2% below current price
    
    result = open_limit_position(
        symbol="BTCUSDT",
        side="long",
        entry_price=entry_price,
        leverage=5.0,
        size_pct=0.15,
        sl_pct=0.02
    )
    
    print(f"Status: {result.get('status')}")
    print(f"Order ID: {result.get('exchange_order_id')}")
    print(f"Order Link ID: {result.get('exchange_order_link_id')}")
    print(f"Intent ID: {result.get('intent_id')}")
    print(f"Entry Price: {result.get('entry_price')}")
    print(f"Expires At: {result.get('expires_at')}")
    print()


if __name__ == "__main__":
    print("\n")
    print("*" * 60)
    print("LIMIT ENTRY ORDER INTEGRATION EXAMPLES")
    print("*" * 60)
    print("\n")
    
    # NOTE: These examples are for documentation purposes.
    # Uncomment to run actual requests (requires running position manager).
    
    # example_market_entry()
    # example_limit_entry_simple()
    
    print("Examples defined. Uncomment in __main__ to run with live position manager.")
    print()
