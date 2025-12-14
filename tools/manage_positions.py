#!/usr/bin/env python3
"""
Utility script to test Master AI /manage_critical_positions endpoint.
Uses only Python stdlib - no external dependencies.

Usage:
  # From host machine (if ports are exposed)
  python tools/manage_positions.py --host localhost --port 8004

  # From within docker network
  docker exec -it orchestrator python /app/tools/manage_positions.py --host 04_master_ai_agent --port 8000
  
  # With custom test data
  python tools/manage_positions.py --host localhost --port 8004 --symbol BTCUSDT --side long --entry 42000 --mark 40000 --leverage 5
"""

import json
import sys
import argparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def call_manage_critical_positions(host, port, positions_data):
    """
    Call Master AI /manage_critical_positions endpoint
    
    Args:
        host: hostname (e.g., 'localhost' or '04_master_ai_agent')
        port: port number (e.g., 8004 or 8000)
        positions_data: list of position dicts
    
    Returns:
        dict: Response from the endpoint
    """
    url = f"http://{host}:{port}/manage_critical_positions"
    
    request_body = {
        "positions": positions_data,
        "portfolio_snapshot": {
            "equity": 1000.0,
            "free_balance": 500.0
        }
    }
    
    print(f"\n🔗 Calling: {url}")
    print(f"📤 Request body:")
    print(json.dumps(request_body, indent=2))
    print()
    
    try:
        # Prepare request
        data = json.dumps(request_body).encode('utf-8')
        req = Request(url, data=data, headers={'Content-Type': 'application/json'})
        
        # Make request
        with urlopen(req, timeout=65) as response:
            response_data = response.read().decode('utf-8')
            response_json = json.loads(response_data)
            
            print(f"✅ Response (Status {response.status}):")
            print(json.dumps(response_json, indent=2))
            
            return response_json
            
    except HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else "No error body"
        print(f"❌ HTTP Error {e.code}: {e.reason}")
        print(f"Error body: {error_body}")
        return None
        
    except URLError as e:
        print(f"❌ URL Error: {e.reason}")
        print(f"Hint: Make sure the service is running at {host}:{port}")
        return None
        
    except Exception as e:
        print(f"❌ Unexpected error: {type(e).__name__}: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description='Test Master AI /manage_critical_positions endpoint',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument('--host', default='localhost',
                        help='Hostname (default: localhost)')
    parser.add_argument('--port', type=int, default=8004,
                        help='Port number (default: 8004)')
    
    # Custom position parameters
    parser.add_argument('--symbol', default='BTCUSDT',
                        help='Symbol (default: BTCUSDT)')
    parser.add_argument('--side', default='long', choices=['long', 'short'],
                        help='Position side (default: long)')
    parser.add_argument('--entry', type=float, default=42000.0,
                        help='Entry price (default: 42000.0)')
    parser.add_argument('--mark', type=float, default=40000.0,
                        help='Mark price (default: 40000.0)')
    parser.add_argument('--leverage', type=float, default=5.0,
                        help='Leverage (default: 5.0)')
    parser.add_argument('--size', type=float, default=0.1,
                        help='Position size (default: 0.1)')
    
    # Multi-position test
    parser.add_argument('--multi', action='store_true',
                        help='Test with multiple positions')
    
    args = parser.parse_args()
    
    # Prepare test positions
    if args.multi:
        # Test with multiple positions
        positions = [
            {
                "symbol": "BTCUSDT",
                "side": "long",
                "entry_price": 42000.0,
                "mark_price": 40000.0,
                "leverage": 5.0,
                "size": 0.1,
                "pnl": -100.0,
                "is_disabled": False
            },
            {
                "symbol": "ETHUSDT",
                "side": "short",
                "entry_price": 2200.0,
                "mark_price": 2300.0,
                "leverage": 5.0,
                "size": 1.0,
                "pnl": -50.0,
                "is_disabled": False
            },
            {
                "symbol": "SOLUSDT",
                "side": "long",
                "entry_price": 100.0,
                "mark_price": 95.0,
                "leverage": 5.0,
                "size": 5.0,
                "pnl": -25.0,
                "is_disabled": True  # Test disabled symbol
            }
        ]
    else:
        # Single position test
        positions = [
            {
                "symbol": args.symbol,
                "side": args.side,
                "entry_price": args.entry,
                "mark_price": args.mark,
                "leverage": args.leverage,
                "size": args.size,
                "pnl": -50.0,  # Simulated PnL
                "is_disabled": False
            }
        ]
    
    print("=" * 60)
    print("  Master AI - Critical Position Management Test")
    print("=" * 60)
    
    # Call endpoint
    response = call_manage_critical_positions(args.host, args.port, positions)
    
    if response:
        print("\n" + "=" * 60)
        print("  Summary")
        print("=" * 60)
        
        actions = response.get('actions', [])
        meta = response.get('meta', {})
        
        print(f"\n📊 Total actions: {len(actions)}")
        print(f"⏱️  Processing time: {meta.get('processing_time_ms', 0)}ms")
        print(f"⚠️  Timeout occurred: {meta.get('timeout_occurred', False)}")
        
        print("\n🎯 Actions breakdown:")
        for action in actions:
            symbol = action.get('symbol')
            action_type = action.get('action')
            loss_pct = action.get('loss_pct_with_leverage', 0)
            confidence = action.get('confidence', 0)
            
            print(f"  • {symbol}: {action_type} (loss: {loss_pct:.2f}%, confidence: {confidence}%)")
        
        print("\n✅ Test completed successfully!")
        return 0
    else:
        print("\n❌ Test failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
