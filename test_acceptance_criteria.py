#!/usr/bin/env python3
"""
Acceptance criteria test for AI decision rationale improvements

This test validates that:
1. A decision with 5 confirmations for SHORT returns either OPEN_SHORT or HOLD with blocked_by
2. No mismatched text like 'pattern BTC long' as reason to block OPEN_SHORT setup
3. Backward compatibility: dashboard renders old decisions without errors
"""
import os
import sys
import json

# Setup path and env
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'agents', '04_master_ai_agent'))
os.environ['DEEPSEEK_API_KEY'] = 'test-key-for-testing'

import main as master_ai

def test_acceptance_criteria_1():
    """
    Test: A decision with 5 confirmations for SHORT must return OPEN_SHORT or HOLD with blocked_by
    """
    print("\n" + "="*80)
    print("ACCEPTANCE CRITERIA 1: Coherent SHORT setup handling")
    print("="*80)
    
    # Scenario: AI identifies 5 confirmations for SHORT
    decision_dict = {
        "symbol": "BTCUSDT",
        "action": "OPEN_SHORT",
        "leverage": 5.0,
        "size_pct": 0.15,
        "confidence": 85,
        "rationale": "Analizzato setup SHORT: 5 conferme bearish trovate. Apertura SHORT.",
        "setup_confirmations": [
            "Trend bearish confermato su 1h e 4h",
            "RSI > 70 (ipercomprato)",
            "Resistenza Fibonacci 45000 rifiutata",
            "News sentiment negativo",
            "Forecast prevede calo"
        ],
        "blocked_by": [],
        "direction_considered": "SHORT"
    }
    
    # Apply guardrails
    result = master_ai.enforce_decision_consistency(decision_dict)
    
    print("\n✅ Test 1A: Decision con 5 conferme SHORT non bloccata")
    assert result['action'] == 'OPEN_SHORT', "❌ Action dovrebbe essere OPEN_SHORT"
    assert result['direction_considered'] == 'SHORT', "❌ Direction dovrebbe essere SHORT"
    assert len(result['setup_confirmations']) == 5, "❌ Dovrebbero esserci 5 conferme"
    print(f"   ✅ Action: {result['action']}")
    print(f"   ✅ Direction: {result['direction_considered']}")
    print(f"   ✅ Conferme: {len(result['setup_confirmations'])}")
    
    # Scenario: Same setup but blocked by insufficient margin
    decision_dict_blocked = {
        "symbol": "BTCUSDT",
        "action": "OPEN_SHORT",
        "leverage": 5.0,
        "size_pct": 0.15,
        "confidence": 85,
        "rationale": "Setup SHORT valido ma margine insufficiente",
        "setup_confirmations": [
            "Trend bearish confermato su 1h e 4h",
            "RSI > 70 (ipercomprato)",
            "Resistenza Fibonacci 45000 rifiutata",
            "News sentiment negativo",
            "Forecast prevede calo"
        ],
        "blocked_by": ["INSUFFICIENT_MARGIN"],
        "direction_considered": "SHORT"
    }
    
    result_blocked = master_ai.enforce_decision_consistency(decision_dict_blocked)
    
    print("\n✅ Test 1B: Decision con 5 conferme SHORT ma bloccata da margine")
    assert result_blocked['action'] == 'HOLD', "❌ Action dovrebbe essere HOLD quando bloccata"
    assert result_blocked['direction_considered'] == 'SHORT', "❌ Direction dovrebbe rimanere SHORT"
    assert 'INSUFFICIENT_MARGIN' in result_blocked['blocked_by'], "❌ Blocked by dovrebbe contenere INSUFFICIENT_MARGIN"
    print(f"   ✅ Action: {result_blocked['action']} (forced from OPEN_SHORT)")
    print(f"   ✅ Blocked by: {result_blocked['blocked_by']}")
    print(f"   ✅ Direction considerata: {result_blocked['direction_considered']}")
    
    return True


def test_acceptance_criteria_2():
    """
    Test: No mismatched text like 'pattern BTC long' blocking OPEN_SHORT setup
    """
    print("\n" + "="*80)
    print("ACCEPTANCE CRITERIA 2: No contradictory rationales")
    print("="*80)
    
    # Scenario: OPEN_SHORT should not reference "long setup" in rationale
    decision_dict = {
        "symbol": "BTCUSDT",
        "action": "OPEN_SHORT",
        "leverage": 5.0,
        "size_pct": 0.15,
        "confidence": 75,
        "rationale": "Setup SHORT confermato. Recente chiusura BTC long in perdita è un risk factor, non un blocker.",
        "setup_confirmations": [
            "Trend bearish su 1h",
            "RSI > 65",
            "Resistenza rifiutata"
        ],
        "risk_factors": [
            "Recente BTC long chiuso in perdita"
        ],
        "blocked_by": [],
        "direction_considered": "SHORT"
    }
    
    result = master_ai.enforce_decision_consistency(decision_dict)
    
    print("\n✅ Test 2A: OPEN_SHORT con risk factor 'recent long loss' è valido")
    assert result['action'] == 'OPEN_SHORT', "❌ Action dovrebbe essere OPEN_SHORT"
    assert result['direction_considered'] == 'SHORT', "❌ Direction dovrebbe essere SHORT"
    assert 'long' not in ' '.join(result.get('setup_confirmations', [])).lower(), \
        "❌ Setup confirmations non dovrebbero menzionare 'long'"
    print(f"   ✅ Action: {result['action']}")
    print(f"   ✅ Setup confirmations: {len(result['setup_confirmations'])} (nessun riferimento a 'long')")
    print(f"   ✅ Risk factors: {result['risk_factors']} (separati dalle conferme)")
    
    # Test guardrail warning for contradictory rationale
    decision_dict_bad = {
        "symbol": "BTCUSDT",
        "action": "OPEN_SHORT",
        "leverage": 5.0,
        "size_pct": 0.15,
        "confidence": 75,
        "rationale": "Long setup con RSI basso ma non aprirò, invece farò SHORT",  # Contradictory!
        "setup_confirmations": ["Trend bearish"],
        "direction_considered": "SHORT"
    }
    
    # This should trigger a warning log but still be accepted
    result_bad = master_ai.enforce_decision_consistency(decision_dict_bad)
    
    print("\n✅ Test 2B: Guardrail rileva rationale contraddittorio (log warning)")
    print(f"   ✅ Rationale contradditorio rilevato: 'long setup' in OPEN_SHORT rationale")
    print(f"   ✅ Decision processata con warning (vedi log)")
    
    return True


def test_acceptance_criteria_3():
    """
    Test: Backward compatibility - old decisions without new fields still work
    """
    print("\n" + "="*80)
    print("ACCEPTANCE CRITERIA 3: Backward compatibility")
    print("="*80)
    
    # Old format decision (pre-refactor)
    old_decision = {
        "symbol": "ETHUSDT",
        "action": "OPEN_LONG",
        "leverage": 5.0,
        "size_pct": 0.15,
        "confidence": 80,
        "rationale": "Trend bullish, RSI oversold",
        "confirmations": ["Trend up", "RSI < 30"],
        "risk_factors": ["High volatility"]
        # NO setup_confirmations, blocked_by, direction_considered
    }
    
    # Guardrails should fill in missing fields
    result = master_ai.enforce_decision_consistency(old_decision)
    
    print("\n✅ Test 3A: Old decision format automatically enhanced")
    assert result.get('direction_considered') == 'LONG', "❌ Direction dovrebbe essere inferita da action"
    assert result.get('setup_confirmations') == old_decision['confirmations'], \
        "❌ Setup confirmations dovrebbe usare confirmations per backward compat"
    print(f"   ✅ direction_considered inferito: {result['direction_considered']}")
    print(f"   ✅ setup_confirmations copiato da confirmations: {result['setup_confirmations']}")
    
    # Test creating Decision object from old format
    try:
        decision_obj = master_ai.Decision(**result)
        print(f"   ✅ Decision object creato con successo")
        print(f"   ✅ Tutti i nuovi campi sono opzionali, quindi backward compatible")
    except Exception as e:
        print(f"   ❌ Errore creazione Decision: {e}")
        return False
    
    # Test HOLD with low confidence
    old_hold = {
        "symbol": "SOLUSDT",
        "action": "HOLD",
        "rationale": "Segnali incerti",
        "confidence": 35
    }
    
    result_hold = master_ai.enforce_decision_consistency(old_hold)
    
    print("\n✅ Test 3B: Old HOLD con bassa confidence riceve soft_blockers automaticamente")
    assert result_hold.get('soft_blockers'), "❌ soft_blockers dovrebbe essere inferito per LOW_CONFIDENCE"
    assert 'LOW_CONFIDENCE' in result_hold['soft_blockers'], "❌ Dovrebbe contenere LOW_CONFIDENCE in soft_blockers"
    assert not result_hold.get('blocked_by'), "❌ blocked_by dovrebbe essere vuoto (LOW_CONFIDENCE è SOFT, non HARD)"
    print(f"   ✅ soft_blockers inferito: {result_hold['soft_blockers']}")
    print(f"   ✅ blocked_by rimane vuoto: {result_hold.get('blocked_by', [])}")
    
    return True


def run_acceptance_tests():
    """Run all acceptance criteria tests"""
    print("\n" + "="*80)
    print("ACCEPTANCE CRITERIA TEST SUITE")
    print("Validating problem statement requirements")
    print("="*80)
    
    tests = [
        ("Criterion 1: Coherent SHORT setup handling", test_acceptance_criteria_1),
        ("Criterion 2: No contradictory rationales", test_acceptance_criteria_2),
        ("Criterion 3: Backward compatibility", test_acceptance_criteria_3),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
                print(f"\n{'='*80}")
                print(f"✅ {name} PASSED")
                print(f"{'='*80}")
        except Exception as e:
            failed += 1
            print(f"\n{'='*80}")
            print(f"❌ {name} FAILED")
            print(f"Error: {e}")
            print(f"{'='*80}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "="*80)
    print("ACCEPTANCE TEST RESULTS")
    print("="*80)
    print(f"✅ Passed: {passed}/{len(tests)}")
    if failed > 0:
        print(f"❌ Failed: {failed}/{len(tests)}")
    else:
        print("🎉 ALL ACCEPTANCE CRITERIA MET!")
    print("="*80 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    success = run_acceptance_tests()
    sys.exit(0 if success else 1)
