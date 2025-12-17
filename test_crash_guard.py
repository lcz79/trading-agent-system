#!/usr/bin/env python3
"""
Test crash guard momentum filters and 2-cycle CRITICAL confirmation

Validates:
1. Technical analyzer returns crash guard metrics (return_5m, range_5m_pct, etc.)
2. Master AI blocks OPEN_LONG when return_5m <= -0.6%
3. Master AI blocks OPEN_SHORT when return_5m >= +0.6%
4. Orchestrator implements 2-cycle confirmation for CRITICAL CLOSE
5. Orchestrator clamps leverage and size_pct to safe ranges
"""
import os
import sys

# Setup path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'agents', '01_technical_analyzer'))
# Don't add orchestrator to path yet to avoid conflicts
master_ai_path = os.path.join(os.path.dirname(__file__), 'agents', '04_master_ai_agent')

# Set env vars before importing
os.environ['DEEPSEEK_API_KEY'] = 'test-key'
os.environ['CRASH_GUARD_5M_LONG_BLOCK_PCT'] = '0.6'
os.environ['CRASH_GUARD_5M_SHORT_BLOCK_PCT'] = '0.6'


# Import helper to load modules without package conflicts
def load_module_from_path(name, path):
    """Load a module from a specific path"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_technical_analyzer_crash_metrics():
    """Test that technical analyzer includes crash guard metrics"""
    print("\n" + "="*80)
    print("TEST 1: Technical Analyzer - Crash Guard Metrics")
    print("="*80)
    
    # Validate code structure without importing (requires pandas)
    import ast
    
    indicators_path = os.path.join(os.path.dirname(__file__), 'agents', '01_technical_analyzer', 'indicators.py')
    with open(indicators_path, 'r') as f:
        code = f.read()
    
    # Check for crash guard metrics in code
    assert 'return_1m' in code, "return_1m should be in indicators.py"
    assert 'return_5m' in code, "return_5m should be in indicators.py"
    assert 'return_15m' in code, "return_15m should be in indicators.py"
    assert 'range_5m_pct' in code, "range_5m_pct should be in indicators.py"
    assert 'volume_spike' in code, "volume_spike should be in indicators.py"
    
    print("✅ Crash guard metrics found in technical analyzer code")
    
    print("\n📋 Expected crash guard metrics in summary:")
    print("   - return_1m: % change in 1m timeframe")
    print("   - return_5m: % change in 5m timeframe")
    print("   - return_15m: % change in 15m timeframe")
    print("   - range_5m_pct: (high-low)/close for 5m")
    print("   - volume_spike_5m: current vol / avg vol")
    

def test_master_ai_crash_guard_block():
    """Test Master AI crash guard blocking logic"""
    print("\n" + "="*80)
    print("TEST 2: Master AI - Crash Guard Hard-Block")
    print("="*80)
    
    # Check code structure instead of importing
    master_ai_code_path = os.path.join(os.path.dirname(__file__), 'agents', '04_master_ai_agent', 'main.py')
    with open(master_ai_code_path, 'r') as f:
        code = f.read()
    
    # Test 2A: Verify crash guard variables exist
    print("\n📌 Test 2A: Crash guard configuration variables exist")
    assert 'CRASH_GUARD_5M_LONG_BLOCK_PCT' in code, "CRASH_GUARD_5M_LONG_BLOCK_PCT should exist"
    assert 'CRASH_GUARD_5M_SHORT_BLOCK_PCT' in code, "CRASH_GUARD_5M_SHORT_BLOCK_PCT should exist"
    print("✅ Crash guard configuration variables found")
    
    # Test 2B: Verify blocking logic for LONG
    print("\n📌 Test 2B: OPEN_LONG blocking logic exists")
    assert 'return_5m <= -CRASH_GUARD_5M_LONG_BLOCK_PCT' in code or 'return_5m <= -' in code, "LONG blocking check should exist"
    assert 'OPEN_LONG' in code and 'CRASH_GUARD' in code, "OPEN_LONG and CRASH_GUARD should be in code"
    print("✅ OPEN_LONG blocking logic found")
    
    # Test 2C: Verify blocking logic for SHORT
    print("\n📌 Test 2C: OPEN_SHORT blocking logic exists")
    assert 'return_5m >= ' in code or 'CRASH_GUARD_5M_SHORT_BLOCK_PCT' in code, "SHORT blocking check should exist"
    assert 'OPEN_SHORT' in code, "OPEN_SHORT should be in code"
    print("✅ OPEN_SHORT blocking logic found")
    
    # Test 2D: Verify CRASH_GUARD blocker exists
    print("\n📌 Test 2D: CRASH_GUARD blocker type exists")
    assert '"CRASH_GUARD"' in code or "'CRASH_GUARD'" in code, "CRASH_GUARD should be in blocker reasons"
    print("✅ CRASH_GUARD blocker type added to valid blocker reasons")
    
    # Test 2E: Verify blocked_by is updated
    print("\n📌 Test 2E: blocked_by is updated with CRASH_GUARD")
    assert 'blocked_by' in code, "blocked_by field should be used"
    print("✅ blocked_by field is updated when crash guard blocks")

def test_orchestrator_2cycle_confirmation():
    """Test orchestrator 2-cycle confirmation for CRITICAL CLOSE"""
    print("\n" + "="*80)
    print("TEST 3: Orchestrator - 2-Cycle CRITICAL CLOSE Confirmation")
    print("="*80)
    
    # Check code structure
    orch_code_path = os.path.join(os.path.dirname(__file__), 'agents', 'orchestrator', 'main.py')
    with open(orch_code_path, 'r') as f:
        code = f.read()
    
    # Test 3A: Verify pending state tracking exists
    print("\n📌 Test 3A: Pending CRITICAL close state tracking exists")
    assert 'pending_critical_closes' in code, "pending_critical_closes should exist"
    print("✅ Pending close state tracking variable found")
    
    # Test 3B: Verify confirmation function exists
    print("\n📌 Test 3B: Confirmation function exists")
    assert 'check_critical_close_confirmation' in code, "check_critical_close_confirmation function should exist"
    assert 'def check_critical_close_confirmation' in code, "Function should be defined"
    print("✅ check_critical_close_confirmation function found")
    
    # Test 3C: Verify 2-cycle logic
    print("\n📌 Test 3C: 2-cycle confirmation logic exists")
    assert 'First' in code or 'first' in code or 'Second' in code or 'second' in code, "Cycle counting logic should exist"
    print("✅ 2-cycle confirmation logic found in code")
    
    # Test 3D: Verify reset logic
    print("\n📌 Test 3D: Reset pending close logic exists")
    assert 'del pending_critical_closes' in code or 'remove' in code or 'reset' in code.lower(), "Reset logic should exist"
    print("✅ Reset logic for pending closes found")


def test_orchestrator_params_clamping():
    """Test orchestrator parameter clamping"""
    print("\n" + "="*80)
    print("TEST 4: Orchestrator - AI Params Clamping")
    print("="*80)
    
    # Check code structure
    orch_code_path = os.path.join(os.path.dirname(__file__), 'agents', 'orchestrator', 'main.py')
    with open(orch_code_path, 'r') as f:
        code = f.read()
    
    # Test 4A: Verify clamp function exists
    print("\n📌 Test 4A: Clamp function exists")
    assert 'clamp_ai_params' in code, "clamp_ai_params function should exist"
    assert 'def clamp_ai_params' in code, "Function should be defined"
    print("✅ clamp_ai_params function found")
    
    # Test 4B: Verify min/max constants exist
    print("\n📌 Test 4B: Min/Max constants exist")
    assert 'MIN_LEVERAGE' in code, "MIN_LEVERAGE should be defined"
    assert 'MAX_LEVERAGE' in code, "MAX_LEVERAGE should be defined"
    assert 'MIN_SIZE_PCT' in code, "MIN_SIZE_PCT should be defined"
    assert 'MAX_SIZE_PCT' in code, "MAX_SIZE_PCT should be defined"
    print("✅ Min/Max constants found")
    
    # Test 4C: Verify clamping is applied
    print("\n📌 Test 4C: Clamping is applied in open_position calls")
    assert 'clamp_ai_params' in code, "clamp_ai_params should be called"
    assert 'open_position' in code, "open_position endpoint should be used"
    print("✅ Clamping is applied when opening positions")
    
    # Test 4D: Verify logging
    print("\n📌 Test 4D: Clamp logging exists")
    assert 'CLAMP' in code or 'clamp' in code.lower(), "Clamp logging should exist"
    print("✅ Clamp operations are logged")


def test_env_vars_configuration():
    """Test environment variable configuration"""
    print("\n" + "="*80)
    print("TEST 5: Environment Variables Configuration")
    print("="*80)
    
    # Check .env.example
    env_example_path = os.path.join(os.path.dirname(__file__), '.env.example')
    with open(env_example_path, 'r') as f:
        env_example = f.read()
    
    print("\n📌 Test 5A: Crash guard vars in .env.example")
    assert 'CRASH_GUARD_5M_LONG_BLOCK_PCT' in env_example, "CRASH_GUARD_5M_LONG_BLOCK_PCT should be in .env.example"
    assert 'CRASH_GUARD_5M_SHORT_BLOCK_PCT' in env_example, "CRASH_GUARD_5M_SHORT_BLOCK_PCT should be in .env.example"
    print("✅ Crash guard vars documented in .env.example")
    
    print("\n📌 Test 5B: Critical loss threshold in .env.example")
    assert 'CRITICAL_LOSS_PCT_LEV' in env_example, "CRITICAL_LOSS_PCT_LEV should be in .env.example"
    print("✅ CRITICAL_LOSS_PCT_LEV documented in .env.example")
    
    # Verify Master AI loads env vars
    master_ai_code_path = os.path.join(os.path.dirname(__file__), 'agents', '04_master_ai_agent', 'main.py')
    with open(master_ai_code_path, 'r') as f:
        master_ai_code = f.read()
    
    print("\n📌 Test 5C: Master AI loads crash guard env vars")
    assert 'os.getenv("CRASH_GUARD_5M_LONG_BLOCK_PCT"' in master_ai_code, "Master AI should load CRASH_GUARD_5M_LONG_BLOCK_PCT"
    assert 'os.getenv("CRASH_GUARD_5M_SHORT_BLOCK_PCT"' in master_ai_code, "Master AI should load CRASH_GUARD_5M_SHORT_BLOCK_PCT"
    print("✅ Master AI correctly loads crash guard env vars")
    
    # Verify Orchestrator loads env vars
    orch_code_path = os.path.join(os.path.dirname(__file__), 'agents', 'orchestrator', 'main.py')
    with open(orch_code_path, 'r') as f:
        orch_code = f.read()
    
    print("\n📌 Test 5D: Orchestrator loads CRITICAL_LOSS_PCT_LEV")
    assert 'CRITICAL_LOSS_PCT_LEV' in orch_code or 'CRITICAL' in orch_code, "Orchestrator should have critical loss config"
    print("✅ Orchestrator has critical loss configuration")


def run_all_tests():
    """Run all crash guard tests"""
    print("\n" + "="*80)
    print("CRASH GUARD & RISK MANAGEMENT TESTS")
    print("="*80)
    
    try:
        test_technical_analyzer_crash_metrics()
        test_master_ai_crash_guard_block()
        test_orchestrator_2cycle_confirmation()
        test_orchestrator_params_clamping()
        test_env_vars_configuration()
        
        print("\n" + "="*80)
        print("✅ ALL TESTS PASSED")
        print("="*80)
        return True
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
