#!/usr/bin/env python3
"""
Test script for the authentication service
"""
import requests

BASE_URL = "http://localhost:8001"

def test_auth_service():
    print("🧪 Testing Authentication Service\n")
    
    # Test 1: Check service is running
    print("1. Testing service health...")
    try:
        response = requests.get(f"{BASE_URL}/")
        print(f"   ✓ Service is running: {response.json()}")
    except Exception as e:
        print(f"   ✗ Service not accessible: {e}")
        return
    
    # Test 2: Register a new user
    print("\n2. Testing user registration...")
    user_data = {
        "email": "test@example.com",
        "username": "testuser",
        "password": "testpass123"
    }
    
    try:
        response = requests.post(f"{BASE_URL}/register", json=user_data)
        if response.status_code == 200:
            print(f"   ✓ User registered: {response.json()['username']}")
        elif response.status_code == 400:
            print(f"   ℹ User already exists (expected if running multiple times)")
        else:
            print(f"   ✗ Registration failed: {response.text}")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    # Test 3: Login
    print("\n3. Testing user login...")
    login_data = {
        "username": "testuser",
        "password": "testpass123"
    }
    
    try:
        response = requests.post(f"{BASE_URL}/login", json=login_data)
        if response.status_code == 200:
            token = response.json()['access_token']
            print(f"   ✓ Login successful, token received")
            
            # Test 4: Get user info
            print("\n4. Testing authenticated endpoint...")
            headers = {"Authorization": f"Bearer {token}"}
            response = requests.get(f"{BASE_URL}/me", headers=headers)
            if response.status_code == 200:
                user = response.json()
                print(f"   ✓ User info retrieved: {user['username']} ({user['email']})")
            else:
                print(f"   ✗ Failed to get user info: {response.text}")
            
            # Test 5: Add exchange key
            print("\n5. Testing exchange key management...")
            key_data = {
                "exchange_name": "bybit",
                "api_key": "test_api_key_123",
                "api_secret": "test_secret_456"
            }
            response = requests.post(f"{BASE_URL}/exchange-keys", json=key_data, headers=headers)
            if response.status_code == 200:
                print(f"   ✓ Exchange key added")
            else:
                print(f"   ✗ Failed to add key: {response.text}")
            
            # Test 6: Get exchange keys
            print("\n6. Testing get exchange keys...")
            response = requests.get(f"{BASE_URL}/exchange-keys", headers=headers)
            if response.status_code == 200:
                keys = response.json()
                print(f"   ✓ Retrieved {len(keys)} key(s)")
                for key in keys:
                    print(f"      - {key['exchange_name']} (added {key['created_at']})")
            else:
                print(f"   ✗ Failed to get keys: {response.text}")
            
            # Test 7: Get bot config
            print("\n7. Testing bot configuration...")
            response = requests.get(f"{BASE_URL}/bot-config", headers=headers)
            if response.status_code == 200:
                config = response.json()
                print(f"   ✓ Bot config retrieved:")
                print(f"      - Running: {config['is_running']}")
                print(f"      - Symbols: {config['symbols']}")
                print(f"      - Position size: ${config['qty_usdt']}")
                print(f"      - Leverage: {config['leverage']}x")
            else:
                print(f"   ✗ Failed to get config: {response.text}")
            
            # Test 8: Update bot config
            print("\n8. Testing bot config update...")
            update_data = {
                "is_running": True,
                "symbols": ["BTCUSDT", "ETHUSDT"],
                "qty_usdt": 100,
                "leverage": 10
            }
            response = requests.put(f"{BASE_URL}/bot-config", json=update_data, headers=headers)
            if response.status_code == 200:
                config = response.json()
                print(f"   ✓ Bot config updated")
                print(f"      - Running: {config['is_running']}")
                print(f"      - Symbols: {config['symbols']}")
            else:
                print(f"   ✗ Failed to update config: {response.text}")
            
        else:
            print(f"   ✗ Login failed: {response.text}")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    print("\n" + "="*50)
    print("✅ Test completed!")
    print("="*50)

if __name__ == "__main__":
    test_auth_service()
