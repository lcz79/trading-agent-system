#!/usr/bin/env python3
"""
Standalone test for learning context helper functions.
Tests the logic without requiring FastAPI dependencies.
"""
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any


def calculate_performance(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate performance metrics from trade list"""
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_duration": 0,
            "max_drawdown": 0.0,
            "winning_trades": 0,
            "losing_trades": 0,
        }
    
    completed_trades = [t for t in trades if t.get('pnl_pct') is not None]
    
    if not completed_trades:
        return {
            "total_trades": len(trades),
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_duration": 0,
            "max_drawdown": 0.0,
            "winning_trades": 0,
            "losing_trades": 0,
        }
    
    total_pnl = sum(t.get('pnl_pct', 0) for t in completed_trades)
    winning_trades = [t for t in completed_trades if t.get('pnl_pct', 0) > 0]
    losing_trades = [t for t in completed_trades if t.get('pnl_pct', 0) <= 0]
    
    win_rate = len(winning_trades) / len(completed_trades) if completed_trades else 0
    
    durations = [t.get('duration_minutes', 0) for t in completed_trades if t.get('duration_minutes')]
    avg_duration = sum(durations) / len(durations) if durations else 0
    
    # Simple drawdown calculation
    cumulative_pnl = 0
    peak = 0
    max_drawdown = 0
    for trade in completed_trades:
        cumulative_pnl += trade.get('pnl_pct', 0)
        peak = max(peak, cumulative_pnl)
        drawdown = peak - cumulative_pnl
        max_drawdown = max(max_drawdown, drawdown)
    
    return {
        "total_trades": len(completed_trades),
        "win_rate": round(win_rate, 4),
        "total_pnl": round(total_pnl, 2),
        "avg_duration": round(avg_duration, 0),
        "max_drawdown": round(max_drawdown, 2),
        "winning_trades": len(winning_trades),
        "losing_trades": len(losing_trades),
    }


def calculate_per_symbol_stats(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate per-symbol aggregated stats"""
    by_symbol = {}
    
    for trade in trades:
        if trade.get('pnl_pct') is None:
            continue
            
        symbol = trade.get('symbol', 'UNKNOWN')
        if symbol not in by_symbol:
            by_symbol[symbol] = {
                'trades': [],
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'total_pnl': 0.0,
                'durations': []
            }
        
        pnl = trade.get('pnl_pct', 0)
        by_symbol[symbol]['trades'].append(trade)
        by_symbol[symbol]['total_trades'] += 1
        by_symbol[symbol]['total_pnl'] += pnl
        
        if pnl > 0:
            by_symbol[symbol]['winning_trades'] += 1
        else:
            by_symbol[symbol]['losing_trades'] += 1
        
        duration = trade.get('duration_minutes')
        if duration is not None:
            by_symbol[symbol]['durations'].append(duration)
    
    # Calculate final metrics per symbol
    result = {}
    for symbol, data in by_symbol.items():
        total = data['total_trades']
        if total == 0:
            continue
        
        win_rate = data['winning_trades'] / total if total > 0 else 0
        avg_pnl = data['total_pnl'] / total if total > 0 else 0
        avg_duration = sum(data['durations']) / len(data['durations']) if data['durations'] else 0
        
        # Calculate max drawdown per symbol
        cumulative_pnl = 0
        peak = 0
        max_dd = 0
        for t in data['trades']:
            cumulative_pnl += t.get('pnl_pct', 0)
            peak = max(peak, cumulative_pnl)
            drawdown = peak - cumulative_pnl
            max_dd = max(max_dd, drawdown)
        
        result[symbol] = {
            'total_trades': total,
            'win_rate': round(win_rate, 4),
            'total_pnl': round(data['total_pnl'], 2),
            'avg_pnl': round(avg_pnl, 2),
            'max_drawdown': round(max_dd, 2),
            'avg_duration': round(avg_duration, 0)
        }
    
    return result


def calculate_risk_flags(trades: List[Dict[str, Any]], performance: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate risk flags based on heuristics"""
    flags = {
        'losing_streak_count': 0,
        'last_trade_pnl_pct': 0.0,
        'negative_pnl_period': False,
        'high_drawdown_period': False
    }
    
    if not trades:
        return flags
    
    # Calculate losing streak
    losing_streak = 0
    for trade in reversed(trades):
        pnl = trade.get('pnl_pct', 0)
        if pnl <= 0:
            losing_streak += 1
        else:
            break
    
    flags['losing_streak_count'] = losing_streak
    
    # Last trade PnL
    if trades:
        flags['last_trade_pnl_pct'] = round(trades[-1].get('pnl_pct', 0), 2)
    
    # Negative PnL period
    total_pnl = performance.get('total_pnl', 0)
    flags['negative_pnl_period'] = total_pnl < 0
    
    # High drawdown period
    max_dd = performance.get('max_drawdown', 0)
    flags['high_drawdown_period'] = max_dd > 10.0
    
    return flags


def test_calculate_performance():
    """Test performance calculation"""
    print("\n" + "="*60)
    print("Test: Calculate Performance")
    print("="*60)
    
    trades = [
        {"pnl_pct": 2.5, "duration_minutes": 120},
        {"pnl_pct": 1.8, "duration_minutes": 90},
        {"pnl_pct": -1.2, "duration_minutes": 60},
        {"pnl_pct": 3.0, "duration_minutes": 150},
    ]
    
    result = calculate_performance(trades)
    
    print(f"Total trades: {result['total_trades']}")
    print(f"Win rate: {result['win_rate']*100:.1f}%")
    print(f"Total PnL: {result['total_pnl']:.2f}%")
    print(f"Winning: {result['winning_trades']} | Losing: {result['losing_trades']}")
    
    assert result['total_trades'] == 4
    assert result['winning_trades'] == 3
    assert result['losing_trades'] == 1
    assert result['total_pnl'] == 6.1
    assert result['win_rate'] == 0.75
    
    print("✅ Test PASSED")


def test_empty_trades():
    """Test with empty trades list"""
    print("\n" + "="*60)
    print("Test: Empty Trades Resilience")
    print("="*60)
    
    result = calculate_performance([])
    
    print(f"Result for empty list: {result}")
    
    assert result['total_trades'] == 0
    assert result['win_rate'] == 0.0
    assert result['total_pnl'] == 0.0
    
    print("✅ Test PASSED")


def test_per_symbol_stats():
    """Test per-symbol statistics"""
    print("\n" + "="*60)
    print("Test: Per-Symbol Stats")
    print("="*60)
    
    trades = [
        {"symbol": "BTCUSDT", "pnl_pct": 2.5, "duration_minutes": 120},
        {"symbol": "BTCUSDT", "pnl_pct": -1.0, "duration_minutes": 90},
        {"symbol": "ETHUSDT", "pnl_pct": 1.8, "duration_minutes": 60},
        {"symbol": "BTCUSDT", "pnl_pct": 3.0, "duration_minutes": 150},
    ]
    
    result = calculate_per_symbol_stats(trades)
    
    print(f"BTCUSDT stats: {result.get('BTCUSDT', {})}")
    print(f"ETHUSDT stats: {result.get('ETHUSDT', {})}")
    
    assert "BTCUSDT" in result
    assert "ETHUSDT" in result
    assert result["BTCUSDT"]["total_trades"] == 3
    assert result["ETHUSDT"]["total_trades"] == 1
    assert result["BTCUSDT"]["win_rate"] == round(2/3, 4)
    
    print("✅ Test PASSED")


def test_risk_flags():
    """Test risk flags calculation"""
    print("\n" + "="*60)
    print("Test: Risk Flags")
    print("="*60)
    
    trades = [
        {"pnl_pct": 2.5},
        {"pnl_pct": 1.8},
        {"pnl_pct": -1.2},
        {"pnl_pct": -0.8},
        {"pnl_pct": -1.5},  # Last 3 are losses = losing streak of 3
    ]
    
    performance = calculate_performance(trades)
    flags = calculate_risk_flags(trades, performance)
    
    print(f"Losing streak: {flags['losing_streak_count']}")
    print(f"Last trade PnL: {flags['last_trade_pnl_pct']:.2f}%")
    print(f"Negative PnL period: {flags['negative_pnl_period']}")
    print(f"High drawdown: {flags['high_drawdown_period']}")
    
    assert flags['losing_streak_count'] == 3
    assert flags['last_trade_pnl_pct'] == -1.5
    assert not flags['negative_pnl_period']  # Overall PnL should still be positive
    
    print("✅ Test PASSED")


def test_learning_context_structure():
    """Test complete learning context structure"""
    print("\n" + "="*60)
    print("Test: Complete Learning Context Structure")
    print("="*60)
    
    # Sample complete trades for a 48-hour period
    trades = [
        {
            "timestamp": (datetime.now() - timedelta(hours=40)).isoformat(),
            "symbol": "BTCUSDT",
            "side": "long",
            "pnl_pct": 2.5,
            "duration_minutes": 120
        },
        {
            "timestamp": (datetime.now() - timedelta(hours=30)).isoformat(),
            "symbol": "ETHUSDT",
            "side": "short",
            "pnl_pct": 1.8,
            "duration_minutes": 90
        },
        {
            "timestamp": (datetime.now() - timedelta(hours=20)).isoformat(),
            "symbol": "BTCUSDT",
            "side": "long",
            "pnl_pct": -1.2,
            "duration_minutes": 60
        },
    ]
    
    # Calculate all components
    performance = calculate_performance(trades)
    by_symbol = calculate_per_symbol_stats(trades)
    risk_flags = calculate_risk_flags(trades, performance)
    
    # Simulate learning context response
    learning_context = {
        "status": "success",
        "period_hours": 48,
        "as_of": datetime.now().isoformat(),
        "performance": performance,
        "recent_trades": trades,
        "by_symbol": by_symbol,
        "risk_flags": risk_flags
    }
    
    print("Learning Context Structure:")
    print(json.dumps(learning_context, indent=2, default=str)[:500] + "...")
    
    # Verify structure
    assert learning_context["status"] == "success"
    assert "performance" in learning_context
    assert "recent_trades" in learning_context
    assert "by_symbol" in learning_context
    assert "risk_flags" in learning_context
    
    # Verify performance structure
    assert "total_trades" in performance
    assert "win_rate" in performance
    assert "total_pnl" in performance
    
    # Verify by_symbol structure
    assert "BTCUSDT" in by_symbol
    assert "total_trades" in by_symbol["BTCUSDT"]
    assert "win_rate" in by_symbol["BTCUSDT"]
    
    # Verify risk_flags structure
    assert "losing_streak_count" in risk_flags
    assert "last_trade_pnl_pct" in risk_flags
    assert "negative_pnl_period" in risk_flags
    assert "high_drawdown_period" in risk_flags
    
    print("✅ Test PASSED")


def main():
    """Run all tests"""
    print("="*60)
    print("LEARNING CONTEXT UNIT TESTS")
    print("="*60)
    
    try:
        test_calculate_performance()
        test_empty_trades()
        test_per_symbol_stats()
        test_risk_flags()
        test_learning_context_structure()
        
        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED")
        print("="*60)
        print("\nSummary:")
        print("- calculate_performance() works correctly")
        print("- calculate_per_symbol_stats() works correctly")
        print("- calculate_risk_flags() works correctly")
        print("- Learning context structure is complete")
        print("- Empty/edge cases handled gracefully")
        return 0
    
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
