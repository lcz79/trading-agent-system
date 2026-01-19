#!/usr/bin/env python3
"""
Demo script showing opportunistic LIMIT feature in action.

This demonstrates how the Master AI can propose a conservative LIMIT order
when the main decision is HOLD but a good opportunity exists.
"""

import json
from datetime import datetime


def demo_opportunistic_limit_scenario():
    """
    Scenario: ETH is in a consolidation/RANGE regime.
    - RSI indicates no clear entry setup (insufficient confirmations)
    - Price is near Fibonacci support at 3500
    - Main decision is HOLD due to low confidence
    - But there's a valid opportunistic LIMIT opportunity at support
    """
    
    print("=" * 80)
    print("DEMO: Opportunistic LIMIT Feature")
    print("=" * 80)
    print()
    
    # 1. Market Context
    print("📊 MARKET CONTEXT")
    print("-" * 80)
    print("Symbol: ETHUSDT")
    print("Current Price: 3510 USDT")
    print("Regime: RANGE (consolidation)")
    print("RSI 15m: 48 (neutral, no clear oversold)")
    print("RSI 1h: 52 (neutral)")
    print("ADX: 18 (weak trend)")
    print("Fibonacci 0.618 support: 3500 USDT (0.28% away)")
    print()
    
    # 2. Master AI Decision
    print("🤖 MASTER AI DECISION")
    print("-" * 80)
    
    ai_decision = {
        "timestamp": datetime.now().isoformat(),
        "symbol": "ETHUSDT",
        "action": "HOLD",
        "direction_considered": "NONE",
        "setup_confirmations": [],
        "blocked_by": [],
        "soft_blockers": ["LOW_CONFIDENCE", "CONFLICTING_SIGNALS"],
        "confidence": 58,
        "rationale": (
            "Main setup insufficient: RSI neutral at 48, ADX weak at 18, "
            "no clear directional bias. However, price approaching key Fib 0.618 "
            "support at 3500 (0.28% away). Conservative opportunistic LIMIT proposed "
            "to capture potential bounce if support holds."
        ),
        "leverage": 1.0,
        "size_pct": 0.0,
        "tp_pct": None,
        "sl_pct": None,
        "entry_type": "MARKET",
        
        # Opportunistic LIMIT proposed
        "opportunistic_limit": {
            "side": "LONG",
            "entry_price": 3500.0,
            "entry_expires_sec": 180,  # 3 minutes
            "tp_pct": 0.015,  # 1.5% target
            "sl_pct": 0.010,  # 1.0% risk
            "rr": 1.5,  # Risk/Reward ratio
            "edge_score": 74,
            "reasoning_bullets": [
                "Price at Fib 0.618 support (3500 USDT)",
                "Recent volume spike near support suggests buying interest",
                "1h trend neutral (no opposition)",
                "Support held 3 times in last 24h",
                "Conservative entry with tight SL and reasonable TP"
            ],
            # Added by validation (risk-based sizing)
            "leverage": 3.5,
            "size_pct": 0.092,
            "notional_usdt": 15.2,
            "margin_required": 4.34
        }
    }
    
    print(f"Action: {ai_decision['action']}")
    print(f"Confidence: {ai_decision['confidence']}%")
    print(f"Rationale: {ai_decision['rationale']}")
    print()
    
    # 3. Opportunistic LIMIT Details
    print("🎯 OPPORTUNISTIC LIMIT PROPOSED")
    print("-" * 80)
    opp = ai_decision["opportunistic_limit"]
    print(f"Side: {opp['side']}")
    print(f"Entry Price: {opp['entry_price']} USDT")
    print(f"Current Price: 3510 USDT (distance: 0.28%)")
    print(f"Expires In: {opp['entry_expires_sec']} seconds")
    print(f"Take Profit: {opp['tp_pct']*100:.1f}% → Target: {opp['entry_price'] * (1 + opp['tp_pct']):.2f} USDT")
    print(f"Stop Loss: {opp['sl_pct']*100:.1f}% → SL: {opp['entry_price'] * (1 - opp['sl_pct']):.2f} USDT")
    print(f"Risk/Reward: {opp['rr']:.2f}x")
    print(f"Edge Score: {opp['edge_score']}/100")
    print()
    print("Reasoning:")
    for i, reason in enumerate(opp['reasoning_bullets'], 1):
        print(f"  {i}. {reason}")
    print()
    
    # 4. Gate Validation
    print("🔒 SAFETY GATE VALIDATION")
    print("-" * 80)
    
    validation_checks = [
        ("✅", "Action is HOLD", True),
        ("✅", "No hard blockers present", True),
        ("✅", f"RR {opp['rr']} >= 1.5", True),
        ("✅", f"TP {opp['tp_pct']*100:.1f}% >= 1.0%", True),
        ("✅", f"SL {opp['sl_pct']*100:.1f}% within bounds [0.25%, 2.5%]", True),
        ("✅", f"Expires {opp['entry_expires_sec']}s within [60, 300]", True),
        ("✅", "Entry price 0.28% from current (< 0.8%)", True),
        ("✅", "Volatility sufficient (0.0012 > 0.0010)", True),
        ("✅", "Risk-based sizing applied", True),
        ("✅", "Conservative leverage (3.5x)", True),
    ]
    
    for emoji, check, passed in validation_checks:
        print(f"{emoji} {check}")
    
    print()
    print("🎉 ALL GATES PASSED - ORDER APPROVED")
    print()
    
    # 5. Orchestrator Mapping
    print("🔄 ORCHESTRATOR MAPPING")
    print("-" * 80)
    
    pm_payload = {
        "symbol": "ETHUSDT",
        "side": "OPEN_LONG",
        "leverage": opp["leverage"],
        "size_pct": opp["size_pct"],
        "entry_type": "LIMIT",
        "entry_price": opp["entry_price"],
        "entry_ttl_sec": opp["entry_expires_sec"],
        "tp_pct": opp["tp_pct"],
        "sl_pct": opp["sl_pct"],
        "intent_id": "abc123...",
        "features": {
            "opportunistic": True,
            "rr": opp["rr"],
            "edge_score": opp["edge_score"],
            "reasoning": opp["reasoning_bullets"],
            "original_action": "HOLD"
        }
    }
    
    print("Position Manager Payload:")
    print(json.dumps(pm_payload, indent=2))
    print()
    
    # 6. Expected Outcome
    print("📈 EXPECTED OUTCOME")
    print("-" * 80)
    print("1. LIMIT order placed at 3500 USDT")
    print("2. Order expires in 3 minutes if not filled")
    print("3. If filled:")
    print(f"   - Entry: 3500 USDT")
    print(f"   - Take Profit: {3500 * (1 + opp['tp_pct']):.2f} USDT (+{opp['tp_pct']*100:.1f}%)")
    print(f"   - Stop Loss: {3500 * (1 - opp['sl_pct']):.2f} USDT (-{opp['sl_pct']*100:.1f}%)")
    print(f"   - Position Size: {opp['size_pct']*100:.1f}% of available (~{opp['notional_usdt']:.1f} USDT notional)")
    print(f"   - Leverage: {opp['leverage']:.1f}x (conservative)")
    print(f"   - Margin Required: {opp['margin_required']:.2f} USDT")
    print("4. Order marked as 'opportunistic' in telemetry")
    print()
    
    # 7. Advantages
    print("✨ ADVANTAGES OF OPPORTUNISTIC LIMIT")
    print("-" * 80)
    print("✅ Captures opportunities even when main setup is weak")
    print("✅ Conservative: only with good RR and at key levels")
    print("✅ No overtrading: respects all existing guardrails")
    print("✅ LIMIT-only: precise entry, no slippage")
    print("✅ Time-bound: expires if opportunity doesn't materialize")
    print("✅ Risk-managed: full risk-based sizing applied")
    print("✅ Transparent: full reasoning and scoring visible")
    print()
    
    print("=" * 80)
    print("DEMO COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    demo_opportunistic_limit_scenario()
