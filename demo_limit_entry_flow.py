#!/usr/bin/env python3
"""
Integration demo: Show how DeepSeek would produce LIMIT entries with sample market data.

This script demonstrates the expected flow:
1. Technical analyzer provides multi-timeframe data
2. Fibonacci agent provides support/resistance levels
3. Master AI uses formulas to compute entry_price
4. Orchestrator maps fields to position manager
5. Position manager creates LIMIT intent with TTL
"""

import json

def create_sample_market_data():
    """Create sample aggregated market data for ETH in RANGE setup"""
    return {
        "ETHUSDT": {
            "technical": {
                "timeframes": {
                    "15m": {
                        "price": 3520.0,
                        "trend": "neutral",
                        "rsi": 32,
                        "macd": -15.2,
                        "macd_momentum": "FALLING",
                        "ema_20": 3540.0,
                        "ema_50": 3560.0,
                        "ema_200": 3550.0,
                        "adx": 18.5,
                        "atr": 42.0,
                        "return_15m": -0.35,
                        "volume_spike_15m": False,
                        "range_15m_pct": 1.2
                    },
                    "1h": {
                        "price": 3520.0,
                        "trend": "neutral",
                        "rsi": 38,
                        "macd": -8.5,
                        "macd_momentum": "FALLING",
                        "ema_20": 3545.0,
                        "ema_50": 3555.0,
                        "ema_200": 3550.0,
                        "adx": 16.2,
                        "atr": 85.0,
                        "return_1h": -0.42,
                        "volume_spike": False
                    },
                    "4h": {
                        "price": 3520.0,
                        "trend": "bearish",
                        "rsi": 45,
                        "adx": 14.8,
                        "return_4h": -1.2
                    },
                    "1d": {
                        "price": 3520.0,
                        "trend": "neutral",
                        "rsi": 48,
                        "adx": 12.5,
                        "return_1d": -0.8
                    }
                },
                "summary": {
                    "return_5m": -0.15
                }
            },
            "fibonacci": {
                "fib_levels": {
                    "fibonacci_0_786": 3510.0,  # Strong support
                    "fibonacci_0_618": 3490.0,
                    "fibonacci_1_272": 3680.0,  # Resistance
                    "fibonacci_1_618": 3720.0
                },
                "nearest_support": 3510.0,
                "nearest_resistance": 3680.0
            },
            "gann": {
                "next_important_levels": {
                    "support_1": 3508.0,
                    "resistance_1": 3675.0
                }
            },
            "news": {
                "sentiment": "neutral",
                "score": 0.02
            },
            "forecast": {
                "prediction_1h": "neutral_to_slightly_bullish",
                "confidence": 0.62
            },
            "fase2_metrics": {
                "volatility_pct": 0.0119,  # 1.19% ATR/price
                "atr": 42.0,
                "trend_strength": 0.0028,  # Low (RANGE regime)
                "regime": "RANGE",
                "adx": 18.5,
                "ema_20": 3540.0,
                "ema_200": 3550.0
            },
            "pre_score": {
                "LONG": {"base_confidence": 52, "breakdown": {}},
                "SHORT": {"base_confidence": 38, "breakdown": {}}
            },
            "range_score": {
                "LONG": {"base_confidence": 68, "breakdown": {"regime_gate": 20, "location_points": 35}},
                "SHORT": {"base_confidence": 22, "breakdown": {}}
            }
        }
    }


def demonstrate_limit_entry_logic():
    """Demonstrate how DeepSeek would compute LIMIT entry for RANGE setup"""
    print("=" * 80)
    print("LIMIT ENTRY COMPUTATION DEMONSTRATION")
    print("=" * 80 + "\n")
    
    market_data = create_sample_market_data()
    eth_data = market_data["ETHUSDT"]
    
    # Extract key data
    current_price = eth_data["technical"]["timeframes"]["15m"]["price"]
    rsi_15m = eth_data["technical"]["timeframes"]["15m"]["rsi"]
    rsi_1h = eth_data["technical"]["timeframes"]["1h"]["rsi"]
    trend_1h = eth_data["technical"]["timeframes"]["1h"]["trend"]
    trend_4h = eth_data["technical"]["timeframes"]["4h"]["trend"]
    atr = eth_data["technical"]["timeframes"]["15m"]["atr"]
    fib_support = eth_data["fibonacci"]["fib_levels"]["fibonacci_0_786"]
    regime = eth_data["fase2_metrics"]["regime"]
    range_score_long = eth_data["range_score"]["LONG"]["base_confidence"]
    
    print(f"📊 Market Context for ETHUSDT:")
    print(f"   Current Price: ${current_price}")
    print(f"   Regime: {regime}")
    print(f"   RSI 15m: {rsi_15m} (oversold)")
    print(f"   RSI 1h: {rsi_1h} (aligned)")
    print(f"   Trend 1h: {trend_1h}")
    print(f"   Trend 4h: {trend_4h} (slightly bearish, not blocking)")
    print(f"   Fibonacci 0.786 support: ${fib_support}")
    print(f"   ATR: ${atr}")
    print(f"   Range Score LONG: {range_score_long}")
    print()
    
    # Step 1: Check if LIMIT entry is appropriate
    print("📝 Step 1: Evaluate LIMIT Entry Appropriateness")
    distance_to_support = abs(current_price - fib_support) / current_price
    print(f"   Distance to Fib support: {distance_to_support*100:.2f}%")
    
    use_limit = False
    if regime == "RANGE" and distance_to_support < 0.005 and range_score_long >= 50:
        use_limit = True
        print(f"   ✅ LIMIT entry appropriate:")
        print(f"      - RANGE regime")
        print(f"      - Price within 0.5% of support")
        print(f"      - Range score >= 50 ({range_score_long})")
    else:
        print(f"   ❌ Use MARKET entry instead")
    
    if not use_limit:
        return
    
    # Step 2: Compute entry_price using formula from prompt
    print()
    print("📝 Step 2: Compute entry_price (LONG at support)")
    print(f"   Formula: entry_price = fib_support * (1 - 0.001)")
    entry_price = fib_support * (1 - 0.001)
    print(f"   entry_price = {fib_support} * 0.999 = ${entry_price:.2f}")
    print(f"   This is -0.03% below support for better fill probability")
    
    # Step 3: Determine TTL based on setup strength
    print()
    print("📝 Step 3: Determine entry_expires_sec (TTL)")
    setup_strength = "normal"  # Based on confidence/confirmations
    if rsi_15m < 30 and rsi_1h < 40 and range_score_long > 65:
        setup_strength = "strong"
        ttl = 120
    elif range_score_long >= 50:
        setup_strength = "normal"
        ttl = 180
    else:
        setup_strength = "weak"
        ttl = 300
    
    print(f"   Setup strength: {setup_strength}")
    print(f"   entry_expires_sec: {ttl}s")
    print(f"   Rationale: {'Strong oversold signal' if setup_strength == 'strong' else 'Normal RANGE setup'}")
    
    # Step 4: Multi-timeframe check
    print()
    print("📝 Step 4: Multi-Timeframe Confirmation Check")
    print(f"   15m: RSI {rsi_15m} oversold ✅")
    print(f"   1h: trend {trend_1h}, RSI {rsi_1h} ✅ (not blocking)")
    print(f"   4h: trend {trend_4h} ⚠️ (slightly bearish, reduce leverage)")
    print(f"   Verdict: OPEN allowed, but reduce leverage from 5x to 4x")
    
    # Step 5: Generate final decision
    print()
    print("=" * 80)
    print("📋 FINAL AI DECISION (as DeepSeek would generate)")
    print("=" * 80)
    
    decision = {
        "symbol": "ETHUSDT",
        "action": "OPEN_LONG",
        "leverage": 4.0,  # Reduced due to 4h bearish
        "size_pct": 0.10,  # Reduced due to 4h caution
        "confidence": 72,
        "rationale": (
            "Playbook: RANGE LONG mean-reversion. 15m RSI=32 oversold + Fib 0.786 support at 3510 "
            f"(distance {distance_to_support*100:.2f}%). 1h trend neutral (no block), RSI 1h=38 aligned. "
            "4h slightly bearish → reduced leverage to 4x and size to 0.10. "
            f"LIMIT entry at ${entry_price:.2f} (-0.03% below support) for precise entry. "
            f"TTL {ttl}s: if not filled quickly, setup invalidated. "
            "Multi-TF check passed with caution."
        ),
        "setup_confirmations": [
            "RSI 15m oversold=32",
            "RSI 1h=38 (aligned)",
            "Fib 0.786 support 3510",
            f"Price near support {distance_to_support*100:.2f}%",
            f"Range score LONG={range_score_long}",
            "1h trend neutral (no veto)"
        ],
        "blocked_by": [],
        "soft_blockers": [],
        "direction_considered": "LONG",
        "entry_type": "LIMIT",
        "entry_price": entry_price,
        "entry_expires_sec": ttl,
        "tp_pct": 0.018,  # 1.8% price = ~7.2% ROI with 4x leverage
        "sl_pct": 0.012,  # 1.2% price = ~4.8% ROI risk with 4x leverage
        "time_in_trade_limit_sec": 3600,
        "cooldown_sec": 900,
        "trail_activation_roi": 0.015  # 1.5% leveraged ROI to activate trailing
    }
    
    print(json.dumps(decision, indent=2))
    
    # Step 6: Orchestrator mapping
    print()
    print("=" * 80)
    print("📤 ORCHESTRATOR MAPPING TO POSITION MANAGER")
    print("=" * 80)
    
    pm_payload = {
        "symbol": decision["symbol"],
        "side": decision["action"],
        "leverage": decision["leverage"],
        "size_pct": decision["size_pct"],
        "intent_id": "demo-intent-001",
        "entry_type": decision["entry_type"],
        "entry_price": decision["entry_price"],
        "entry_ttl_sec": decision["entry_expires_sec"],  # MAPPED!
        "tp_pct": decision["tp_pct"],
        "sl_pct": decision["sl_pct"],
        "time_in_trade_limit_sec": decision["time_in_trade_limit_sec"],
        "cooldown_sec": decision["cooldown_sec"],
        "trail_activation_roi": decision["trail_activation_roi"],
        "features": decision  # Full decision as telemetry
    }
    
    print(json.dumps(pm_payload, indent=2))
    
    # Step 7: Position manager actions
    print()
    print("=" * 80)
    print("🎯 POSITION MANAGER ACTIONS")
    print("=" * 80)
    print(f"1. Create OrderIntent with intent_id='demo-intent-001'")
    print(f"2. Submit LIMIT order to Bybit:")
    print(f"   - Symbol: ETHUSDT")
    print(f"   - Side: Buy (LONG)")
    print(f"   - Type: Limit")
    print(f"   - Price: ${entry_price:.2f}")
    print(f"   - Qty: (calculated from size_pct * wallet * leverage / price)")
    print(f"   - orderLinkId: 'demo-intent-001' (for tracking)")
    print(f"   - timeInForce: GTC")
    print(f"3. Store intent with status=PENDING")
    print(f"4. Set expires_at: {ttl}s from now")
    print(f"5. Monitor order status every 30s:")
    print(f"   - If FILLED → Set SL via trading_stop, mark intent EXECUTED")
    print(f"   - If TTL expired → Cancel order, mark intent CANCELLED")
    print(f"   - If new AI decision with different price → Cancel+Replace")
    print()
    print("✅ LIMIT entry flow complete!")
    

def main():
    demonstrate_limit_entry_logic()


if __name__ == "__main__":
    main()
