#!/usr/bin/env python3
"""
Test script per verificare il funzionamento del Master AI refactorato
"""
import os
import sys
import json
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'agents', '04_master_ai_agent'))

# Set required env vars
os.environ['DEEPSEEK_API_KEY'] = 'test-key-for-testing'

# Import after setting env
import main as master_ai

def test_cooldown_system():
    """Test 1: Sistema di cooldown"""
    print("\n" + "="*60)
    print("TEST 1: Sistema di Cooldown")
    print("="*60)
    
    # Use temp directory for testing
    import tempfile
    original_file = master_ai.RECENT_CLOSES_FILE
    with tempfile.TemporaryDirectory() as tmpdir:
        master_ai.RECENT_CLOSES_FILE = os.path.join(tmpdir, "recent_closes.json")
        
        # Salva un evento di chiusura
        print("\n1. Salvo chiusura ETHUSDT long...")
        master_ai.save_close_event("ETHUSDT", "long", "Trend bearish su tutti TF")
        
        # Carica chiusure recenti
        print("2. Carico chiusure recenti (ultimi 15 minuti)...")
        recent = master_ai.load_recent_closes(15)
        
        assert len(recent) > 0, "❌ Nessuna chiusura trovata!"
        print(f"   ✅ Trovate {len(recent)} chiusure recenti")
        print(f"   Symbol: {recent[0]['symbol']}")
        print(f"   Side: {recent[0]['side']}")
        print(f"   Reason: {recent[0]['reason']}")
        
        # Test chiusure oltre il cooldown
        print("\n3. Test chiusure oltre cooldown (ultimi 1 secondo)...")
        very_recent = master_ai.load_recent_closes(minutes=0.016)  # ~1 secondo
        print(f"   ✅ Chiusure nell'ultimo secondo: {len(very_recent)}")
        
        # Restore original file
        master_ai.RECENT_CLOSES_FILE = original_file
    
    print("\n✅ TEST 1 PASSED: Sistema cooldown funziona correttamente")
    return True


def test_performance_calculation():
    """Test 2: Calcolo performance"""
    print("\n" + "="*60)
    print("TEST 2: Calcolo Performance")
    print("="*60)
    
    # Crea trade di test
    test_trades = [
        {'symbol': 'BTC', 'side': 'long', 'pnl_pct': 5.5},
        {'symbol': 'ETH', 'side': 'short', 'pnl_pct': -3.2},
        {'symbol': 'SOL', 'side': 'long', 'pnl_pct': 2.8},
        {'symbol': 'BTC', 'side': 'long', 'pnl_pct': -1.5},
        {'symbol': 'ETH', 'side': 'short', 'pnl_pct': 4.2},
    ]
    
    print("\n1. Calcolo performance su 5 trade...")
    perf = master_ai.calculate_performance(test_trades)
    
    print(f"\n   Risultati:")
    print(f"   - Total trades: {perf['total_trades']}")
    print(f"   - Win rate: {perf['win_rate']*100:.1f}%")
    print(f"   - Total PnL: {perf['total_pnl']:.2f}%")
    print(f"   - Max drawdown: {perf['max_drawdown']:.2f}%")
    print(f"   - Winning trades: {perf['winning_trades']}")
    print(f"   - Losing trades: {perf['losing_trades']}")
    
    assert perf['total_trades'] == 5, "❌ Numero trade errato!"
    assert perf['winning_trades'] == 3, "❌ Trade vincenti errati!"
    assert perf['losing_trades'] == 2, "❌ Trade perdenti errati!"
    assert abs(perf['total_pnl'] - 7.8) < 0.1, "❌ PnL totale errato!"
    
    print("\n✅ TEST 2 PASSED: Calcolo performance corretto")
    return True


def test_normalize_position_side():
    """Test 3: Normalizzazione side"""
    print("\n" + "="*60)
    print("TEST 3: Normalizzazione Position Side")
    print("="*60)
    
    test_cases = [
        ("long", "long"),
        ("LONG", "long"),
        ("buy", "long"),
        ("BUY", "long"),
        ("short", "short"),
        ("SHORT", "short"),
        ("sell", "short"),
        ("SELL", "short"),
        ("invalid", None),
        ("", None),
    ]
    
    print("\n1. Test normalizzazione...")
    for input_val, expected in test_cases:
        result = master_ai.normalize_position_side(input_val)
        status = "✅" if result == expected else "❌"
        print(f"   {status} '{input_val}' -> '{result}' (expected: '{expected}')")
        assert result == expected, f"❌ Normalizzazione fallita per '{input_val}'"
    
    print("\n✅ TEST 3 PASSED: Normalizzazione funziona correttamente")
    return True


def test_system_prompt():
    """Test 4: Verifica SYSTEM_PROMPT"""
    print("\n" + "="*60)
    print("TEST 4: Verifica System Prompt")
    print("="*60)
    
    prompt = master_ai.SYSTEM_PROMPT
    
    # Verifica presenza keywords chiave
    keywords = [
        "TRADER PROFESSIONISTA",
        "CONFERME NECESSARIE",
        "almeno 3",
        "GESTIONE RISCHIO DINAMICA",
        "Confidenza",
        "HOLD",
        "REGOLE DI COERENZA",
        "PROCESSO DECISIONALE STRUTTURATO",
        "OUTPUT JSON OBBLIGATORIO",
    ]
    
    print("\n1. Verifica keywords nel prompt...")
    for keyword in keywords:
        assert keyword in prompt, f"❌ Keyword '{keyword}' non trovata!"
        print(f"   ✅ '{keyword}' presente")
    
    # Verifica che NON ci siano regole hardcoded
    bad_keywords = [
        "RSI < 35",
        "DEVI ordinare",
        "Leverage suggerito: 5x",
    ]
    
    print("\n2. Verifica rimozione regole hardcoded...")
    for bad_keyword in bad_keywords:
        assert bad_keyword not in prompt, f"❌ Regola hardcoded trovata: '{bad_keyword}'"
        print(f"   ✅ '{bad_keyword}' rimossa")
    
    print(f"\n3. Lunghezza prompt: {len(prompt)} caratteri")
    assert len(prompt) > 1500, "❌ Prompt troppo corto!"
    
    print("\n✅ TEST 4 PASSED: System prompt corretto")
    return True


def test_decision_model():
    """Test 5: Modello Decision"""
    print("\n" + "="*60)
    print("TEST 5: Modello Decision con nuovi campi strutturati")
    print("="*60)
    
    print("\n1. Test creazione Decision con tutti i nuovi campi...")
    
    # Test con tutti i campi inclusi i nuovi
    decision_dict = {
        "symbol": "ETHUSDT",
        "action": "OPEN_LONG",
        "leverage": 7.5,
        "size_pct": 0.20,
        "rationale": "Trend bullish confermato",
        "confidence": 85,
        "confirmations": ["RSI < 30", "Trend 1h bullish", "Fibonacci support"],
        "risk_factors": ["High volatility"],
        "setup_confirmations": ["RSI oversold < 30", "Trend 1h e 4h bullish", "Supporto Fibonacci a 2800"],
        "blocked_by": [],
        "direction_considered": "LONG"
    }
    
    decision = master_ai.Decision(**decision_dict)
    print(f"   ✅ Decision creata:")
    print(f"      Symbol: {decision.symbol}")
    print(f"      Action: {decision.action}")
    print(f"      Confidence: {decision.confidence}%")
    print(f"      Confirmations: {len(decision.confirmations or [])} items")
    print(f"      Risk factors: {len(decision.risk_factors or [])} items")
    print(f"      Setup confirmations: {len(decision.setup_confirmations or [])} items")
    print(f"      Blocked by: {decision.blocked_by}")
    print(f"      Direction considered: {decision.direction_considered}")
    
    # Test senza campi opzionali
    print("\n2. Test Decision senza campi opzionali...")
    minimal_decision = master_ai.Decision(
        symbol="BTCUSDT",
        action="HOLD",
        rationale="Waiting for confirmation"
    )
    print(f"   ✅ Decision minimale creata")
    
    # Test decision con blocked_by
    print("\n3. Test Decision con blocked_by...")
    blocked_decision = master_ai.Decision(
        symbol="SOLUSDT",
        action="HOLD",
        rationale="Margine insufficiente per aprire posizione",
        blocked_by=["INSUFFICIENT_MARGIN"],
        direction_considered="SHORT",
        setup_confirmations=["Trend bearish confermato", "RSI > 60"]
    )
    assert blocked_decision.blocked_by == ["INSUFFICIENT_MARGIN"], "❌ Blocked by non corretto!"
    assert blocked_decision.direction_considered == "SHORT", "❌ Direction non corretta!"
    print(f"   ✅ Decision bloccata creata correttamente")
    print(f"      Blocked by: {blocked_decision.blocked_by}")
    print(f"      Direction: {blocked_decision.direction_considered}")
    
    # Verifica che non ci siano più validators restrittivi
    print("\n4. Test leverage e size senza limiti forzati...")
    high_leverage_decision = master_ai.Decision(
        symbol="SOLUSDT",
        action="OPEN_SHORT",
        leverage=10.0,  # Max leverage
        size_pct=0.25,  # Max size
        rationale="High confidence trade"
    )
    assert high_leverage_decision.leverage == 10.0, "❌ Leverage modificato!"
    assert high_leverage_decision.size_pct == 0.25, "❌ Size modificato!"
    print(f"   ✅ Leverage 10x e size 25% accettati senza modifiche")
    
    print("\n✅ TEST 5 PASSED: Modello Decision con nuovi campi corretto")
    return True


def test_agent_urls():
    """Test 6: Configurazione Agent URLs"""
    print("\n" + "="*60)
    print("TEST 6: Configurazione Agent URLs")
    print("="*60)
    
    print("\n1. Verifica URLs agenti...")
    required_agents = ["technical", "fibonacci", "gann", "news", "forecaster"]
    
    for agent in required_agents:
        assert agent in master_ai.AGENT_URLS, f"❌ Agent '{agent}' non configurato!"
        url = master_ai.AGENT_URLS[agent]
        print(f"   ✅ {agent}: {url}")
    
    print(f"\n2. Learning Agent URL: {master_ai.LEARNING_AGENT_URL}")
    
    print("\n✅ TEST 6 PASSED: Agent URLs configurati correttamente")
    return True


def test_guardrails():
    """Test 7: Guardrails per coerenza decisioni"""
    print("\n" + "="*60)
    print("TEST 7: Guardrails per coerenza decisioni")
    print("="*60)
    
    print("\n1. Test inferenza direction_considered da action...")
    decision_dict = {
        "symbol": "ETHUSDT",
        "action": "OPEN_SHORT",
        "rationale": "Trend bearish",
        "confidence": 75
    }
    result = master_ai.enforce_decision_consistency(decision_dict)
    assert result['direction_considered'] == 'SHORT', "❌ Direction non inferita correttamente!"
    print(f"   ✅ OPEN_SHORT -> direction_considered='SHORT'")
    
    print("\n2. Test correzione incoerenza direction...")
    decision_dict = {
        "symbol": "BTCUSDT",
        "action": "OPEN_LONG",
        "direction_considered": "SHORT",  # Incoerente!
        "rationale": "Test",
        "confidence": 60
    }
    result = master_ai.enforce_decision_consistency(decision_dict)
    assert result['direction_considered'] == 'LONG', "❌ Direction non corretta!"
    print(f"   ✅ OPEN_LONG con direction='SHORT' corretto a 'LONG'")
    
    print("\n3. Test inferenza blocked_by per bassa confidence...")
    decision_dict = {
        "symbol": "SOLUSDT",
        "action": "HOLD",
        "rationale": "Incerto",
        "confidence": 40  # Bassa confidence
    }
    result = master_ai.enforce_decision_consistency(decision_dict)
    assert 'LOW_CONFIDENCE' in result.get('blocked_by', []), "❌ Blocked by non inferito!"
    print(f"   ✅ HOLD con confidence=40 -> blocked_by=['LOW_CONFIDENCE']")
    
    print("\n4. Test forzatura HOLD quando blocked_by presente...")
    decision_dict = {
        "symbol": "ETHUSDT",
        "action": "OPEN_LONG",  # Inconsistente con blocked_by
        "blocked_by": ["INSUFFICIENT_MARGIN"],
        "rationale": "Voglio aprire ma non ho margine",
        "confidence": 80,
        "leverage": 5,
        "size_pct": 0.2
    }
    result = master_ai.enforce_decision_consistency(decision_dict)
    assert result['action'] == 'HOLD', "❌ Action non forzato a HOLD!"
    assert result['leverage'] == 1.0, "❌ Leverage non azzerato!"
    assert result['size_pct'] == 0.0, "❌ Size non azzerato!"
    print(f"   ✅ OPEN_LONG con blocked_by forzato a HOLD")
    
    print("\n5. Test backward compatibility setup_confirmations...")
    decision_dict = {
        "symbol": "BTCUSDT",
        "action": "OPEN_SHORT",
        "confirmations": ["RSI > 70", "Trend bearish"],
        "rationale": "Short setup",
        "confidence": 85
    }
    result = master_ai.enforce_decision_consistency(decision_dict)
    assert result.get('setup_confirmations') == ["RSI > 70", "Trend bearish"], "❌ Setup confirmations non copiato!"
    print(f"   ✅ confirmations copiato a setup_confirmations per backward compat")
    
    print("\n✅ TEST 7 PASSED: Guardrails funzionano correttamente")
    return True


def run_all_tests():
    """Esegui tutti i test"""
    print("\n" + "="*60)
    print("MASTER AI REFACTOR - TEST SUITE")
    print("="*60)
    
    tests = [
        test_cooldown_system,
        test_performance_calculation,
        test_normalize_position_side,
        test_system_prompt,
        test_decision_model,
        test_agent_urls,
        test_guardrails,
    ]
    
    passed = 0
    failed = 0
    
    for test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            print(f"\n❌ TEST FAILED: {test_func.__name__}")
            print(f"   Error: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "="*60)
    print("TEST RESULTS")
    print("="*60)
    print(f"✅ Passed: {passed}/{len(tests)}")
    if failed > 0:
        print(f"❌ Failed: {failed}/{len(tests)}")
    else:
        print("🎉 ALL TESTS PASSED!")
    print("="*60 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
