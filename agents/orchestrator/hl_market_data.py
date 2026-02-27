"""
Hyperliquid Market Data for Wyckoff Analysis

Fetches order book L2, funding rates, and open interest
from Hyperliquid for enhanced pattern recognition.
"""

import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("HLMarketData")

# Use mainnet by default, testnet if env says so
HL_TESTNET = os.getenv("HL_TESTNET", "false").lower() == "true"

try:
    from hyperliquid.info import Info
    from hyperliquid.utils import constants

    _API_URL = constants.TESTNET_API_URL if HL_TESTNET else constants.MAINNET_API_URL
    info = Info(_API_URL, skip_ws=True)
    HL_AVAILABLE = True
    logger.info(f"Hyperliquid SDK initialized ({'testnet' if HL_TESTNET else 'mainnet'})")
except ImportError:
    info = None
    HL_AVAILABLE = False
    logger.warning("hyperliquid-python-sdk not installed, Wyckoff data unavailable")


def get_wyckoff_data(symbol: str) -> dict:
    """
    Fetch order book, funding, OI for Wyckoff analysis.

    Args:
        symbol: Trading pair like 'BTCUSDT'

    Returns:
        dict with order_book, funding_rate, open_interest, mark_price
    """
    if not HL_AVAILABLE:
        return _empty_result()

    coin = symbol.replace("USDT", "")

    try:
        # L2 Order Book (top 20 levels)
        l2 = info.l2_snapshot(coin)

        bids = l2["levels"][0][:20]
        asks = l2["levels"][1][:20]

        bid_depth = sum(float(b["sz"]) for b in bids)
        ask_depth = sum(float(a["sz"]) for a in asks)
        total_depth = bid_depth + ask_depth
        imbalance = bid_depth / total_depth if total_depth > 0 else 0.5

        # Meta and asset contexts for funding + OI
        meta = info.meta_and_asset_ctxs()

        current_funding = 0.0
        current_oi = 0.0

        if isinstance(meta, list) and len(meta) >= 2:
            universe = meta[0].get("universe", [])
            asset_ctxs = meta[1]

            for i, asset_info in enumerate(universe):
                if asset_info.get("name") == coin:
                    if i < len(asset_ctxs):
                        ctx = asset_ctxs[i]
                        current_funding = float(ctx.get("funding", 0))
                        current_oi = float(ctx.get("openInterest", 0))
                    break

        # Current mid price
        mids = info.all_mids()
        mark_price = float(mids.get(coin, 0))

        return {
            "order_book": {
                "bids": [{"px": b["px"], "sz": b["sz"]} for b in bids[:10]],
                "asks": [{"px": a["px"], "sz": a["sz"]} for a in asks[:10]],
                "bid_depth": round(bid_depth, 4),
                "ask_depth": round(ask_depth, 4),
                "imbalance": round(imbalance, 4),
            },
            "funding_rate": current_funding,
            "open_interest": current_oi,
            "mark_price": mark_price,
        }

    except Exception as e:
        logger.warning(f"Hyperliquid data fetch failed for {symbol}: {e}")
        return _empty_result()


def _empty_result() -> dict:
    return {
        "order_book": {
            "bids": [],
            "asks": [],
            "bid_depth": 0,
            "ask_depth": 0,
            "imbalance": 0.5,
        },
        "funding_rate": 0.0,
        "open_interest": 0.0,
        "mark_price": 0.0,
    }
