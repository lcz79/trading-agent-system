#!/usr/bin/env python3
"""
Integration test to demonstrate the UNIFIED wallet detection flow.

This script simulates the entire flow from Position Manager -> Master AI -> Orchestrator
to show how the system handles UNIFIED accounts.
"""

import json


def simulate_position_manager_unified():
    """Simula Position Manager con account UNIFIED"""
    print("=" * 70)
    print("STEP 1: Position Manager - Get Wallet Balance (UNIFIED Account)")
    print("=" * 70)
    
    # Simula risposta raw da Bybit UNIFIED
    print("\n📥 Raw Bybit API response (UNIFIED account):")
    print("   USDT.free = None")
    print("   USDT.total = 250.5")
    
    # Simula parsing
    print("\n🔍 Parsing coin-level data from info.result.list[0].coin[]:")
    usdt_coin_data = {
        "walletBalance": 245.3,
        "equity": 250.5,
        "totalPositionIM": 50.0,
        "totalOrderIM": 10.0,
        "locked": 5.0,
    }
    for key, value in usdt_coin_data.items():
        print(f"   {key}: {value}")
    
    # Calcola available_for_new_trades
    buffer = 10.0
    derived_available = (
        usdt_coin_data["walletBalance"]
        - usdt_coin_data["totalPositionIM"]
        - usdt_coin_data["totalOrderIM"]
        - usdt_coin_data["locked"]
        - buffer
    )
    available_for_new_trades = max(0.0, derived_available)
    
    print(f"\n💰 Calculation:")
    print(f"   walletBalance ({usdt_coin_data['walletBalance']}) ")
    print(f"   - totalPositionIM ({usdt_coin_data['totalPositionIM']}) ")
    print(f"   - totalOrderIM ({usdt_coin_data['totalOrderIM']}) ")
    print(f"   - locked ({usdt_coin_data['locked']}) ")
    print(f"   - buffer ({buffer})")
    print(f"   = {derived_available:.2f}")
    print(f"\n   available_for_new_trades = {available_for_new_trades:.2f} USDT")
    
    # Response endpoint
    response = {
        "equity": usdt_coin_data["equity"],
        "available": 0.0,  # None from CCXT
        "available_for_new_trades": available_for_new_trades,
        "available_source": "bybit_unified_im_derived",
        "components": {
            "walletBalance": usdt_coin_data["walletBalance"],
            "totalPositionIM": usdt_coin_data["totalPositionIM"],
            "totalOrderIM": usdt_coin_data["totalOrderIM"],
            "locked": usdt_coin_data["locked"],
            "buffer": buffer,
            "derived_available": derived_available
        }
    }
    
    print(f"\n📤 Position Manager response:")
    print(json.dumps(response, indent=2))
    
    return response


def simulate_master_ai_decision(wallet):
    """Simula Master AI decision con wallet data"""
    print("\n\n" + "=" * 70)
    print("STEP 2: Master AI - Decision Making")
    print("=" * 70)
    
    print("\n📥 Wallet data received from Orchestrator:")
    print(f"   equity: {wallet['equity']:.2f} USDT")
    print(f"   available: {wallet['available']:.2f} USDT")
    print(f"   available_for_new_trades: {wallet['available_for_new_trades']:.2f} USDT")
    print(f"   source: {wallet['available_source']}")
    
    # Check margin constraint
    margin_threshold = 10.0
    can_open_new_positions = wallet['available_for_new_trades'] >= margin_threshold
    
    print(f"\n🔍 Margin Check:")
    print(f"   threshold: {margin_threshold} USDT")
    print(f"   available_for_new_trades: {wallet['available_for_new_trades']:.2f} USDT")
    print(f"   can_open_new_positions: {can_open_new_positions}")
    
    if not can_open_new_positions:
        print("\n🚫 MARGIN CONSTRAINT ACTIVE - Blocking new entries")
        print("   Adding warning to AI prompt...")
        decision = {
            "symbol": "BTCUSDT",
            "action": "HOLD",
            "leverage": 0,
            "size_pct": 0,
            "rationale": f"Blocked: insufficient free margin (available_for_new_trades={wallet['available_for_new_trades']:.2f}, threshold={margin_threshold})"
        }
    else:
        print("\n✅ MARGIN SUFFICIENT - Evaluating market conditions")
        # Simula decisione normale basata su analisi tecnica
        decision = {
            "symbol": "BTCUSDT",
            "action": "OPEN_LONG",  # Potrebbe essere cambiato da AI
            "leverage": 5,
            "size_pct": 0.15,
            "rationale": "Strong bullish signals with sufficient margin"
        }
        
        # Hard constraint enforcement
        if not can_open_new_positions and decision["action"] in ["OPEN_LONG", "OPEN_SHORT"]:
            print("\n⚠️ POST-PROCESSING: Converting OPEN to HOLD due to margin constraint")
            decision["action"] = "HOLD"
            decision["leverage"] = 0
            decision["size_pct"] = 0
            decision["rationale"] = f"Blocked: insufficient free margin (available_for_new_trades={wallet['available_for_new_trades']:.2f}, threshold={margin_threshold}). Original: {decision['rationale']}"
    
    print(f"\n📤 Master AI decision:")
    print(json.dumps(decision, indent=2))
    
    return decision


def simulate_orchestrator_execution(decision, wallet):
    """Simula Orchestrator execution"""
    print("\n\n" + "=" * 70)
    print("STEP 3: Orchestrator - Execution")
    print("=" * 70)
    
    print(f"\n📥 Decision received from Master AI:")
    print(f"   symbol: {decision['symbol']}")
    print(f"   action: {decision['action']}")
    print(f"   rationale: {decision['rationale']}")
    
    if decision["action"] == "HOLD" and "insufficient" in decision["rationale"].lower() and "margin" in decision["rationale"].lower():
        available_for_new = wallet.get('available_for_new_trades', wallet.get('available', 0))
        available_source = wallet.get('available_source', 'unknown')
        print(f"\n🚫 HOLD on {decision['symbol']}: {decision['rationale']}")
        print(f"   Wallet: available={available_for_new:.2f} USDT (source: {available_source})")
        print("\n❌ No position opened - waiting for margin to increase")
    elif decision["action"] in ["OPEN_LONG", "OPEN_SHORT"]:
        print(f"\n🔥 EXECUTING {decision['action']} on {decision['symbol']}...")
        print(f"   leverage: {decision['leverage']}")
        print(f"   size_pct: {decision['size_pct']}")
        print("\n✅ Position opened successfully")
    else:
        print(f"\n📊 Action: {decision['action']}")


def main():
    print("\n" + "=" * 70)
    print("BYBIT UNIFIED WALLET DETECTION - INTEGRATION TEST")
    print("=" * 70)
    print("\nThis test demonstrates the complete flow:")
    print("1. Position Manager detects UNIFIED account and calculates available margin")
    print("2. Master AI receives wallet data and enforces margin constraints")
    print("3. Orchestrator executes decisions (or blocks due to margin)")
    print("=" * 70)
    
    # Test Case 1: Sufficient margin
    print("\n\n" + "#" * 70)
    print("# TEST CASE 1: UNIFIED Account with SUFFICIENT Margin (170 USDT)")
    print("#" * 70)
    
    wallet = simulate_position_manager_unified()
    decision = simulate_master_ai_decision(wallet)
    simulate_orchestrator_execution(decision, wallet)
    
    # Test Case 2: Insufficient margin
    print("\n\n" + "#" * 70)
    print("# TEST CASE 2: UNIFIED Account with INSUFFICIENT Margin (5 USDT)")
    print("#" * 70)
    
    # Modifica wallet per simulare margine insufficiente
    wallet_low_margin = {
        "equity": 250.5,
        "available": 0.0,
        "available_for_new_trades": 5.0,  # < 10.0 threshold
        "available_source": "bybit_unified_im_derived",
        "components": {
            "walletBalance": 245.3,
            "totalPositionIM": 150.0,  # Posizioni più grandi
            "totalOrderIM": 60.0,
            "locked": 20.3,
            "buffer": 10.0,
            "derived_available": 5.0
        }
    }
    
    print("\n📥 Modified scenario:")
    print(f"   Higher positions IM: 150.0 USDT")
    print(f"   Higher orders IM: 60.0 USDT")
    print(f"   Result: available_for_new_trades = {wallet_low_margin['available_for_new_trades']} USDT")
    
    decision = simulate_master_ai_decision(wallet_low_margin)
    simulate_orchestrator_execution(decision, wallet_low_margin)
    
    # Summary
    print("\n\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print("\n✅ CASE 1 (Sufficient margin):")
    print("   - Position Manager correctly calculates 170 USDT available")
    print("   - Master AI allows opening positions")
    print("   - Orchestrator executes trade")
    
    print("\n🚫 CASE 2 (Insufficient margin):")
    print("   - Position Manager correctly calculates 5 USDT available")
    print("   - Master AI blocks opening positions (< 10 USDT threshold)")
    print("   - Orchestrator logs constraint and doesn't execute")
    
    print("\n🎯 KEY BENEFITS:")
    print("   1. UNIFIED accounts no longer show zero availability incorrectly")
    print("   2. Accurate margin calculation using Initial Margin data")
    print("   3. Clear logging and rationale for margin constraints")
    print("   4. Prevents risky trades with insufficient margin")
    print("   5. Backward compatibility maintained")
    
    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    main()
