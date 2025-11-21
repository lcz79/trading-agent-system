import time
import schedule
import requests
import os
import json
import math
import logging
from typing import Dict, List, Optional
from pybit.unified_trading import HTTP

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- CONFIG ---
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://auth-service:8001")
INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "")

# --- URL DEGLI AGENTI ---
URL_BRAIN = "http://master-ai-agent:8000/decide"
URL_TECH = "http://technical-analyzer-agent:8000/analyze_multi_tf"
URL_FIB = "http://fibonacci-cyclical-agent:8000/analyze_fibonacci"
URL_GANN = "http://gann-analyzer-agent:8000/analyze_gann"
URL_MGMT = "http://position-manager-agent:8000/manage"
URL_NEWS = "http://news-sentiment-agent:8000/analyze_sentiment"

instrument_rules_cache = {}

class UserTradingSession:
    """Handles trading operations for a single user"""
    
    def __init__(self, user_id: int, api_key: str, api_secret: str, config: dict):
        self.user_id = user_id
        self.config = config
        self.session = HTTP(testnet=False, api_key=api_key, api_secret=api_secret)
        self.symbols = json.loads(config.get('symbols', '[]'))
        self.qty_usdt = config.get('qty_usdt', 50)
        self.leverage = config.get('leverage', 5)
        logger.info(f"Created trading session for user {user_id}")
    
    def get_instrument_rules(self, symbol: str) -> Optional[dict]:
        """Get trading rules for a symbol"""
        cache_key = f"{self.user_id}_{symbol}"
        if cache_key in instrument_rules_cache:
            return instrument_rules_cache[cache_key]
        
        try:
            response = self.session.get_instruments_info(category="linear", symbol=symbol)
            if response['retCode'] == 0 and response['result']['list']:
                rules = response['result']['list'][0]['lotSizeFilter']
                instrument_rules_cache[cache_key] = rules
                return rules
        except Exception as e:
            logger.error(f"User {self.user_id}: Failed to get rules for {symbol}: {e}")
        return None
    
    def get_data(self, url: str, payload: dict) -> dict:
        """Fetch data from an agent"""
        try:
            r = requests.post(url, json=payload, timeout=40)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            logger.warning(f"User {self.user_id}: Agent at {url} not responding: {e}")
            return {}
    
    def execute_trade(self, setup: dict, symbol: str):
        """Execute a trade based on setup from AI"""
        if not setup:
            logger.error(f"User {self.user_id}: Null setup for {symbol}")
            return
        
        try:
            action = setup.get('decision')
            trade_details = setup.get('trade_setup') or {}
            if not isinstance(trade_details, dict):
                trade_details = {}
            
            side = "Buy" if action == "OPEN_LONG" else "Sell"
            entry = trade_details.get('entry_price')
            sl = trade_details.get('stop_loss')
            tp = trade_details.get('take_profit')
            
            if not all([action, side, entry, sl, tp]):
                logger.error(f"User {self.user_id}: Incomplete setup for {symbol}: {setup}")
                return
            
            rules = self.get_instrument_rules(symbol)
            if not rules:
                logger.error(f"User {self.user_id}: Cannot proceed without trading rules for {symbol}")
                return
            
            qty_step = float(rules.get('qtyStep', '0.001'))
            budget = self.qty_usdt * trade_details.get('size_pct', 0.5)
            raw_qty = (budget * self.leverage) / entry
            
            precision = int(-math.log10(qty_step)) if qty_step < 1 else 0
            qty = math.floor(raw_qty / qty_step) * qty_step
            final_qty_str = f"{qty:.{precision}f}"
            
            logger.info(f"User {self.user_id}: EXECUTING ORDER: {side} {final_qty_str} {symbol} @ {entry} | SL: {sl} | TP: {tp}")
            
            try:
                self.session.set_leverage(
                    category="linear",
                    symbol=symbol,
                    buyLeverage=str(self.leverage),
                    sellLeverage=str(self.leverage)
                )
            except Exception as e:
                if "110043" in str(e):
                    logger.info(f"User {self.user_id}: Leverage already set for {symbol}")
                else:
                    logger.warning(f"User {self.user_id}: Leverage setting issue: {e}")
            
            self.session.place_order(
                category="linear",
                symbol=symbol,
                side=side,
                orderType="Limit",
                qty=final_qty_str,
                price=str(entry),
                timeInForce="GTC",
                stopLoss=str(sl),
                takeProfit=str(tp),
                slTriggerBy="LastPrice",
                tpTriggerBy="LastPrice"
            )
            logger.info(f"User {self.user_id}: Order for {symbol} placed successfully")
        except Exception as e:
            logger.error(f"User {self.user_id}: Order execution failed for {symbol}: {e}")
    
    def get_open_positions(self) -> List[str]:
        """Get list of currently open positions"""
        try:
            response = self.session.get_positions(category="linear", settleCoin="USDT")
            if response['retCode'] == 0 and 'list' in response['result']:
                return [p['symbol'] for p in response['result']['list'] if float(p.get('size', 0)) > 0]
        except Exception as e:
            logger.error(f"User {self.user_id}: Failed to get positions: {e}")
        return []
    
    def run_trading_cycle(self):
        """Execute one trading cycle for this user"""
        logger.info(f"=== User {self.user_id}: Starting trading cycle ===")
        
        open_positions = self.get_open_positions()
        if open_positions:
            logger.info(f"User {self.user_id}: Open positions: {', '.join(open_positions)}")
        
        for symbol in self.symbols:
            if symbol in open_positions:
                logger.info(f"User {self.user_id}: Skipping {symbol} (position already open)")
                continue
            
            logger.info(f"User {self.user_id}: Analyzing {symbol}")
            
            # Gather data from agents
            tech = self.get_data(URL_TECH, {"symbol": symbol})
            fib = self.get_data(URL_FIB, {"crypto_symbol": symbol})
            gann = self.get_data(URL_GANN, {"symbol": symbol})
            sentiment = self.get_data(URL_NEWS, {"symbol": symbol})
            
            # Get decision from AI brain
            logger.info(f"User {self.user_id}: Consulting AI Brain for {symbol}")
            payload = {
                "symbol": symbol,
                "tech_data": tech,
                "fib_data": fib,
                "gann_data": gann,
                "sentiment_data": sentiment
            }
            brain_resp = self.get_data(URL_BRAIN, payload)
            
            if not brain_resp:
                logger.warning(f"User {self.user_id}: No response from AI Brain for {symbol}")
                continue
            
            decision = brain_resp.get("decision", "WAIT")
            logger.info(f"User {self.user_id}: AI Decision for {symbol}: {decision}")
            
            if brain_resp.get("logic_log"):
                for log_entry in brain_resp["logic_log"]:
                    logger.info(f"User {self.user_id}: {log_entry}")
            
            if decision in ["OPEN_LONG", "OPEN_SHORT"]:
                self.execute_trade(brain_resp, symbol)
        
        # Position management
        logger.info(f"User {self.user_id}: Running position management")
        mgmt_resp = self.get_data(URL_MGMT, {"positions": []})
        if mgmt_resp:
            logger.info(f"User {self.user_id}: {len(mgmt_resp)} management actions")
        
        logger.info(f"=== User {self.user_id}: Trading cycle completed ===")


class MultiUserOrchestrator:
    """Orchestrates trading for multiple users"""
    
    def __init__(self):
        self.sessions: Dict[int, UserTradingSession] = {}
        logger.info("Multi-user orchestrator initialized")
    
    def get_active_users(self) -> List[dict]:
        """Fetch active users with running bots from auth service"""
        try:
            headers = {"Authorization": f"Bearer {INTERNAL_SERVICE_TOKEN}"}
            response = requests.get(f"{AUTH_SERVICE_URL}/active-users", headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch active users: {e}")
            return []
    
    def create_user_session(self, user_data: dict) -> Optional[UserTradingSession]:
        """Create a trading session for a user"""
        try:
            user_id = user_data['user_id']
            exchange_name = user_data.get('exchange', 'bybit')
            
            # Get decrypted API keys from auth service with internal token
            headers = {"Authorization": f"Bearer {INTERNAL_SERVICE_TOKEN}"}
            response = requests.get(
                f"{AUTH_SERVICE_URL}/users/{user_id}/exchange-keys/{exchange_name}/decrypt",
                headers=headers,
                timeout=10
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to get keys for user {user_id}")
                return None
            
            keys = response.json()
            session = UserTradingSession(
                user_id=user_id,
                api_key=keys['api_key'],
                api_secret=keys['api_secret'],
                config=user_data['config']
            )
            return session
        except Exception as e:
            logger.error(f"Failed to create session for user {user_data.get('user_id')}: {e}")
            return None
    
    def job(self):
        """Main job that runs periodically"""
        logger.info(f"\n{'='*60}")
        logger.info(f"Starting multi-user trading cycle at {time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{'='*60}")
        
        # Get active users
        active_users = self.get_active_users()
        logger.info(f"Found {len(active_users)} active users")
        
        # Update sessions
        for user_data in active_users:
            user_id = user_data['user_id']
            
            if user_id not in self.sessions:
                # Create new session
                session = self.create_user_session(user_data)
                if session:
                    self.sessions[user_id] = session
            else:
                # Update existing session config
                self.sessions[user_id].config = user_data['config']
                self.sessions[user_id].symbols = json.loads(user_data['config'].get('symbols', '[]'))
                self.sessions[user_id].qty_usdt = user_data['config'].get('qty_usdt', 50)
                self.sessions[user_id].leverage = user_data['config'].get('leverage', 5)
        
        # Remove inactive users (sessions for users who stopped their bot)
        active_user_ids = [u['user_id'] for u in active_users]
        for user_id in list(self.sessions.keys()):
            if user_id not in active_user_ids:
                logger.info(f"Removing inactive user {user_id}")
                del self.sessions[user_id]
        
        # Run trading cycles for all active users
        for user_id, session in self.sessions.items():
            try:
                session.run_trading_cycle()
            except Exception as e:
                logger.error(f"Error in trading cycle for user {user_id}: {e}")
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Multi-user trading cycle completed at {time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{'='*60}\n")


def main():
    """Main entry point"""
    logger.info("🚀 Multi-User Trading Orchestrator Starting...")
    
    orchestrator = MultiUserOrchestrator()
    
    # Run first cycle immediately
    logger.info("Executing first trading cycle...")
    orchestrator.job()
    
    # Schedule periodic runs
    schedule.every(15).minutes.do(orchestrator.job)
    logger.info("⏰ Scheduled to run every 15 minutes")
    
    # Keep running
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
