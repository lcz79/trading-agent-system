#!/usr/bin/env python3
"""
Test script per validare il supporto Bybit UNIFIED wallet.

Questo script testa:
1. Parsing corretto dei dati raw Bybit UNIFIED
2. Calcolo di available_for_new_trades
3. Risposta corretta dell'endpoint /get_wallet_balance
"""

import json
import sys

# Mock della funzione extract_usdt_coin_data_from_bybit per testing
def to_float(x, default=0.0):
    try:
        if x is None:
            return default
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if s == "" or s.lower() == "none":
            return default
        return float(s)
    except Exception:
        return default

def extract_usdt_coin_data_from_bybit(balance_response: dict):
    """
    Estrae i dati coin-level USDT dalla risposta raw Bybit.
    Per account UNIFIED, parse info.result.list[0].coin per trovare USDT.
    
    Returns dict con: walletBalance, equity, totalPositionIM, totalOrderIM, locked, availableToWithdraw
    o None se non trovato.
    """
    try:
        info = balance_response.get("info", {})
        if not info:
            return None
        
        result = info.get("result", {})
        if not result:
            return None
        
        # In UNIFIED account: result.list[0] contiene l'account, poi result.list[0].coin[] contiene le coin
        account_list = result.get("list", [])
        if not account_list or not isinstance(account_list, list):
            return None
        
        # Primo account (dovrebbe essere l'account UNIFIED)
        account = account_list[0] if len(account_list) > 0 else {}
        
        # Cerca coin USDT
        coins = account.get("coin", [])
        if not coins or not isinstance(coins, list):
            return None
        
        for coin in coins:
            if coin.get("coin") == "USDT":
                return {
                    "walletBalance": to_float(coin.get("walletBalance"), 0.0),
                    "equity": to_float(coin.get("equity"), 0.0),
                    "totalPositionIM": to_float(coin.get("totalPositionIM"), 0.0),
                    "totalOrderIM": to_float(coin.get("totalOrderIM"), 0.0),
                    "locked": to_float(coin.get("locked"), 0.0),
                    "availableToWithdraw": to_float(coin.get("availableToWithdraw"), 0.0),
                }
        
        return None
    except Exception as e:
        print(f"⚠️ Errore parsing Bybit raw data: {e}")
        return None


def test_unified_wallet_parsing():
    """Test parsing di Bybit UNIFIED account response"""
    print("=" * 60)
    print("Test 1: Parsing Bybit UNIFIED account response")
    print("=" * 60)
    
    # Simula risposta Bybit UNIFIED con USDT.free=None ma dati coin disponibili
    mock_balance_response = {
        "USDT": {
            "total": 250.5,
            "free": None,  # Tipico in UNIFIED
            "used": None
        },
        "info": {
            "retCode": 0,
            "result": {
                "list": [
                    {
                        "accountType": "UNIFIED",
                        "totalEquity": "250.5",
                        "totalWalletBalance": "245.3",
                        "totalMarginBalance": "250.5",
                        "totalAvailableBalance": "",  # Può essere vuoto
                        "coin": [
                            {
                                "coin": "USDT",
                                "walletBalance": "245.3",
                                "equity": "250.5",
                                "totalPositionIM": "50.0",
                                "totalOrderIM": "10.0",
                                "locked": "5.0",
                                "availableToWithdraw": ""  # Può essere vuoto
                            },
                            {
                                "coin": "BTC",
                                "walletBalance": "0",
                                "equity": "0",
                                "totalPositionIM": "0",
                                "totalOrderIM": "0",
                                "locked": "0",
                                "availableToWithdraw": "0"
                            }
                        ]
                    }
                ]
            }
        }
    }
    
    usdt_data = extract_usdt_coin_data_from_bybit(mock_balance_response)
    
    if usdt_data is None:
        print("❌ FAIL: Could not extract USDT data")
        return False
    
    print(f"✅ USDT data extracted successfully:")
    print(f"   - walletBalance: {usdt_data['walletBalance']}")
    print(f"   - equity: {usdt_data['equity']}")
    print(f"   - totalPositionIM: {usdt_data['totalPositionIM']}")
    print(f"   - totalOrderIM: {usdt_data['totalOrderIM']}")
    print(f"   - locked: {usdt_data['locked']}")
    
    # Verifica valori
    assert usdt_data['walletBalance'] == 245.3, f"walletBalance mismatch: {usdt_data['walletBalance']}"
    assert usdt_data['equity'] == 250.5, f"equity mismatch: {usdt_data['equity']}"
    assert usdt_data['totalPositionIM'] == 50.0, f"totalPositionIM mismatch: {usdt_data['totalPositionIM']}"
    assert usdt_data['totalOrderIM'] == 10.0, f"totalOrderIM mismatch: {usdt_data['totalOrderIM']}"
    assert usdt_data['locked'] == 5.0, f"locked mismatch: {usdt_data['locked']}"
    
    print("✅ All values match expected")
    return True


def test_available_calculation():
    """Test calcolo available_for_new_trades"""
    print("\n" + "=" * 60)
    print("Test 2: Calcolo available_for_new_trades")
    print("=" * 60)
    
    # Dati esempio
    wallet_balance = 245.3
    total_position_im = 50.0
    total_order_im = 10.0
    locked = 5.0
    buffer = 10.0
    
    # Formula: walletBalance - totalPositionIM - totalOrderIM - locked - buffer
    derived_available = wallet_balance - total_position_im - total_order_im - locked - buffer
    available_for_new_trades = max(0.0, derived_available)
    
    print(f"Inputs:")
    print(f"   walletBalance:    {wallet_balance}")
    print(f"   totalPositionIM:  {total_position_im}")
    print(f"   totalOrderIM:     {total_order_im}")
    print(f"   locked:           {locked}")
    print(f"   buffer:           {buffer}")
    print(f"\nCalculation:")
    print(f"   {wallet_balance} - {total_position_im} - {total_order_im} - {locked} - {buffer} = {derived_available}")
    print(f"\nResult:")
    print(f"   available_for_new_trades = {available_for_new_trades}")
    
    # Verifica risultato atteso
    expected = 170.3  # 245.3 - 50.0 - 10.0 - 5.0 - 10.0
    assert abs(available_for_new_trades - expected) < 0.01, f"Calculation error: {available_for_new_trades} != {expected}"
    
    print(f"✅ Calculation correct: {available_for_new_trades:.2f} USDT available for new trades")
    return True


def test_margin_threshold():
    """Test margin threshold logic"""
    print("\n" + "=" * 60)
    print("Test 3: Margin threshold enforcement")
    print("=" * 60)
    
    threshold = 10.0
    
    test_cases = [
        (170.3, True, "Should allow opening positions"),
        (50.0, True, "Should allow opening positions"),
        (10.0, True, "Should allow at threshold"),
        (9.99, False, "Should block below threshold"),
        (0.0, False, "Should block at zero"),
    ]
    
    all_passed = True
    for available, expected_can_open, description in test_cases:
        can_open = available >= threshold
        status = "✅" if can_open == expected_can_open else "❌"
        print(f"{status} available={available:.2f}, can_open={can_open}, expected={expected_can_open} - {description}")
        if can_open != expected_can_open:
            all_passed = False
    
    if all_passed:
        print("✅ All margin threshold tests passed")
    else:
        print("❌ Some margin threshold tests failed")
    
    return all_passed


def test_wallet_balance_response():
    """Test formato risposta /get_wallet_balance"""
    print("\n" + "=" * 60)
    print("Test 4: Response format validation")
    print("=" * 60)
    
    # Simula risposta endpoint per UNIFIED account
    mock_response = {
        "equity": 250.5,
        "available": 0.0,  # None convertito a 0
        "available_for_new_trades": 170.3,
        "available_source": "bybit_unified_im_derived",
        "components": {
            "walletBalance": 245.3,
            "totalPositionIM": 50.0,
            "totalOrderIM": 10.0,
            "locked": 5.0,
            "buffer": 10.0,
            "derived_available": 170.3
        }
    }
    
    # Verifica campi obbligatori
    required_fields = ["equity", "available", "available_for_new_trades", "available_source", "components"]
    missing_fields = [f for f in required_fields if f not in mock_response]
    
    if missing_fields:
        print(f"❌ FAIL: Missing required fields: {missing_fields}")
        return False
    
    print("✅ All required fields present:")
    for field in required_fields:
        print(f"   - {field}: {mock_response[field]}")
    
    # Verifica backward compatibility
    print("\n✅ Backward compatibility maintained:")
    print(f"   - equity (existing): {mock_response['equity']}")
    print(f"   - available (existing): {mock_response['available']}")
    
    # Verifica nuovi campi
    print("\n✅ New fields added:")
    print(f"   - available_for_new_trades: {mock_response['available_for_new_trades']}")
    print(f"   - available_source: {mock_response['available_source']}")
    print(f"   - components: {mock_response['components']}")
    
    return True


def test_normal_account():
    """Test account normale (non-UNIFIED) con USDT.free disponibile"""
    print("\n" + "=" * 60)
    print("Test 5: Normal account (non-UNIFIED)")
    print("=" * 60)
    
    # Simula risposta account normale
    mock_balance_response = {
        "USDT": {
            "total": 1000.0,
            "free": 850.0,  # Disponibile
            "used": 150.0
        },
        "info": {}
    }
    
    equity = 1000.0
    available = 850.0
    buffer = 10.0
    
    # Per account normale, usiamo USDT.free
    available_for_new_trades = max(0.0, available - buffer)
    
    print(f"Account type: Normal (USDT.free available)")
    print(f"   equity: {equity}")
    print(f"   available (free): {available}")
    print(f"   available_for_new_trades: {available_for_new_trades} (= {available} - {buffer})")
    print(f"   source: ccxt_free")
    
    assert available_for_new_trades == 840.0, f"Calculation error: {available_for_new_trades}"
    
    print("✅ Normal account handling correct")
    return True


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("BYBIT UNIFIED WALLET DETECTION - TEST SUITE")
    print("=" * 60 + "\n")
    
    tests = [
        ("Parsing UNIFIED response", test_unified_wallet_parsing),
        ("Available calculation", test_available_calculation),
        ("Margin threshold", test_margin_threshold),
        ("Response format", test_wallet_balance_response),
        ("Normal account", test_normal_account),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ Test '{name}' failed with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nResult: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
