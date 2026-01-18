#!/usr/bin/env python3
"""
Test suite for orchestrator configuration and slot/symbol limits.
Validates that universe scanning and max positions are configurable.
"""

import sys
import os
from pathlib import Path


def test_default_max_positions():
    """Test that MAX_OPEN_POSITIONS defaults to 10"""
    print("\n" + "="*60)
    print("TEST 1: Default MAX_OPEN_POSITIONS = 10")
    print("="*60)
    
    # Clear env var to test default
    if 'MAX_OPEN_POSITIONS' in os.environ:
        del os.environ['MAX_OPEN_POSITIONS']
    
    # Reload the module to get fresh config
    import importlib
    import agents.orchestrator.main as orchestrator
    importlib.reload(orchestrator)
    
    assert orchestrator.MAX_POSITIONS == 10, f"Expected MAX_POSITIONS=10 but got {orchestrator.MAX_POSITIONS}"
    
    print(f"✅ PASS: MAX_POSITIONS defaults to 10")
    print(f"   MAX_POSITIONS: {orchestrator.MAX_POSITIONS}")


def test_custom_max_positions():
    """Test that MAX_OPEN_POSITIONS can be overridden via env var"""
    print("\n" + "="*60)
    print("TEST 2: Custom MAX_OPEN_POSITIONS via env var")
    print("="*60)
    
    # Set custom value
    os.environ['MAX_OPEN_POSITIONS'] = '15'
    
    # Reload the module to get updated config
    import importlib
    import agents.orchestrator.main as orchestrator
    importlib.reload(orchestrator)
    
    assert orchestrator.MAX_POSITIONS == 15, f"Expected MAX_POSITIONS=15 but got {orchestrator.MAX_POSITIONS}"
    
    print(f"✅ PASS: MAX_OPEN_POSITIONS can be customized")
    print(f"   MAX_POSITIONS: {orchestrator.MAX_POSITIONS}")
    
    # Clean up
    del os.environ['MAX_OPEN_POSITIONS']


def test_default_symbol_universe():
    """Test that default symbol universe includes 10 liquid pairs"""
    print("\n" + "="*60)
    print("TEST 3: Default symbol universe has 10+ symbols")
    print("="*60)
    
    # Clear env var to test default
    if 'SCAN_SYMBOLS' in os.environ:
        del os.environ['SCAN_SYMBOLS']
    if 'DISABLED_SYMBOLS' in os.environ:
        del os.environ['DISABLED_SYMBOLS']
    
    # Reload the module
    import importlib
    import agents.orchestrator.main as orchestrator
    importlib.reload(orchestrator)
    
    assert len(orchestrator.SYMBOLS) >= 10, f"Expected at least 10 symbols but got {len(orchestrator.SYMBOLS)}"
    
    # Check that expected symbols are present
    expected_symbols = {'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'ADAUSDT', 
                        'DOGEUSDT', 'AVAXUSDT', 'LINKUSDT', 'BNBUSDT', 'TRXUSDT'}
    
    for sym in expected_symbols:
        assert sym in orchestrator.SYMBOLS, f"Expected symbol {sym} not in universe"
    
    print(f"✅ PASS: Default universe has {len(orchestrator.SYMBOLS)} symbols")
    print(f"   Symbols: {', '.join(orchestrator.SYMBOLS)}")


def test_custom_symbol_universe():
    """Test that SCAN_SYMBOLS can be overridden via env var"""
    print("\n" + "="*60)
    print("TEST 4: Custom SCAN_SYMBOLS via env var")
    print("="*60)
    
    # Set custom symbols
    os.environ['SCAN_SYMBOLS'] = 'BTCUSDT,ETHUSDT,BNBUSDT'
    
    # Reload the module
    import importlib
    import agents.orchestrator.main as orchestrator
    importlib.reload(orchestrator)
    
    expected_symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT']
    assert orchestrator.SYMBOLS == expected_symbols, f"Expected {expected_symbols} but got {orchestrator.SYMBOLS}"
    
    print(f"✅ PASS: Custom SCAN_SYMBOLS works")
    print(f"   Symbols: {', '.join(orchestrator.SYMBOLS)}")
    
    # Clean up
    del os.environ['SCAN_SYMBOLS']


def test_disabled_symbols():
    """Test that DISABLED_SYMBOLS filters out symbols from universe"""
    print("\n" + "="*60)
    print("TEST 5: DISABLED_SYMBOLS filtering")
    print("="*60)
    
    # Set scan symbols and disabled symbols
    os.environ['SCAN_SYMBOLS'] = 'BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT'
    os.environ['DISABLED_SYMBOLS'] = 'SOLUSDT,XRPUSDT'
    
    # Reload the module
    import importlib
    import agents.orchestrator.main as orchestrator
    importlib.reload(orchestrator)
    
    expected_symbols = ['BTCUSDT', 'ETHUSDT']
    assert orchestrator.SYMBOLS == expected_symbols, f"Expected {expected_symbols} but got {orchestrator.SYMBOLS}"
    assert 'SOLUSDT' not in orchestrator.SYMBOLS, "SOLUSDT should be filtered out"
    assert 'XRPUSDT' not in orchestrator.SYMBOLS, "XRPUSDT should be filtered out"
    
    print(f"✅ PASS: DISABLED_SYMBOLS filters correctly")
    print(f"   Active symbols: {', '.join(orchestrator.SYMBOLS)}")
    print(f"   Disabled symbols: {', '.join(orchestrator.DISABLED_SYMBOLS)}")
    
    # Clean up
    del os.environ['SCAN_SYMBOLS']
    del os.environ['DISABLED_SYMBOLS']


def test_orchestrator_uses_max_positions():
    """Test that orchestrator respects MAX_POSITIONS in decision logic"""
    print("\n" + "="*60)
    print("TEST 6: Orchestrator respects MAX_POSITIONS")
    print("="*60)
    
    # Set custom MAX_POSITIONS
    os.environ['MAX_OPEN_POSITIONS'] = '5'
    
    # Reload the module
    import importlib
    import agents.orchestrator.main as orchestrator
    importlib.reload(orchestrator)
    
    # Check that MAX_POSITIONS is used in the code
    # We can verify by checking the module has the correct value
    assert orchestrator.MAX_POSITIONS == 5
    
    # Verify the value is available for use in decision logic
    # (The actual usage is in the analysis_cycle function which we can't easily test without running)
    print(f"✅ PASS: MAX_POSITIONS is properly configured")
    print(f"   MAX_POSITIONS: {orchestrator.MAX_POSITIONS}")
    
    # Clean up
    del os.environ['MAX_OPEN_POSITIONS']


def test_configuration_independence():
    """Test that symbols and max positions are independent configurations"""
    print("\n" + "="*60)
    print("TEST 7: Symbol universe and max positions are independent")
    print("="*60)
    
    # Set both configurations
    os.environ['SCAN_SYMBOLS'] = 'BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,ADAUSDT,DOGEUSDT'
    os.environ['MAX_OPEN_POSITIONS'] = '8'
    
    # Reload the module
    import importlib
    import agents.orchestrator.main as orchestrator
    importlib.reload(orchestrator)
    
    # Should be able to scan 6 symbols with max 8 positions
    # (More positions than symbols in universe)
    assert len(orchestrator.SYMBOLS) == 6
    assert orchestrator.MAX_POSITIONS == 8
    
    print(f"✅ PASS: Configurations are independent")
    print(f"   Universe size: {len(orchestrator.SYMBOLS)}")
    print(f"   Max positions: {orchestrator.MAX_POSITIONS}")
    
    # Clean up
    del os.environ['SCAN_SYMBOLS']
    del os.environ['MAX_OPEN_POSITIONS']


def run_all_tests():
    """Run all test cases"""
    print("\n" + "="*80)
    print(" ORCHESTRATOR CONFIGURATION TEST SUITE")
    print("="*80)
    
    # Add agents directory to path
    sys.path.insert(0, str(Path(__file__).parent / 'agents'))
    
    tests = [
        test_default_max_positions,
        test_custom_max_positions,
        test_default_symbol_universe,
        test_custom_symbol_universe,
        test_disabled_symbols,
        test_orchestrator_uses_max_positions,
        test_configuration_independence,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"\n❌ FAILED: {test.__name__}")
            print(f"   Error: {e}")
            failed += 1
        except Exception as e:
            print(f"\n❌ ERROR in {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "="*80)
    print(f" TEST RESULTS: {passed} passed, {failed} failed")
    print("="*80)
    
    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
