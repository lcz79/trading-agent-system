"""
Unified Trading State Management

This module provides a single source of truth for all trading state including:
- Cooldowns (per symbol+direction)
- Order intents and executions (idempotency)
- Position metadata
- Trailing stop states

All services should use this module instead of managing separate state files.
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from threading import Lock
from dataclasses import dataclass, asdict
from enum import Enum


# State file location
TRADING_STATE_FILE = os.getenv("TRADING_STATE_FILE", "/data/trading_state.json")

# Thread-safe lock for state file operations
_state_lock = Lock()


class OrderStatus(Enum):
    """Status of an order intent"""
    PENDING = "pending"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class OrderIntent:
    """Represents an order intent for idempotency tracking"""
    intent_id: str  # Unique ID for this intent (UUID)
    symbol: str
    action: str  # OPEN_LONG, OPEN_SHORT, CLOSE
    leverage: float
    size_pct: float
    tp_pct: Optional[float] = None
    sl_pct: Optional[float] = None
    time_in_trade_limit_sec: Optional[int] = None
    cooldown_sec: Optional[int] = None
    created_at: str = None  # ISO timestamp
    status: str = OrderStatus.PENDING.value
    exchange_order_id: Optional[str] = None  # Order ID from exchange
    executed_at: Optional[str] = None  # ISO timestamp
    error_message: Optional[str] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()


@dataclass
class Cooldown:
    """Represents a cooldown after closing a position"""
    symbol: str
    direction: str  # long or short
    closed_at: str  # ISO timestamp
    reason: str
    cooldown_sec: int  # Duration in seconds
    
    def is_active(self) -> bool:
        """Check if cooldown is still active"""
        closed = datetime.fromisoformat(self.closed_at)
        expires = closed + timedelta(seconds=self.cooldown_sec)
        return datetime.utcnow() < expires
    
    def expires_at(self) -> datetime:
        """Get expiration timestamp"""
        closed = datetime.fromisoformat(self.closed_at)
        return closed + timedelta(seconds=self.cooldown_sec)


@dataclass
class PositionMetadata:
    """Metadata for an open position"""
    symbol: str
    direction: str  # long or short
    opened_at: str  # ISO timestamp
    intent_id: str  # Link to order intent
    time_in_trade_limit_sec: Optional[int] = None
    entry_price: Optional[float] = None
    size: Optional[float] = None
    leverage: Optional[float] = None
    cooldown_sec: Optional[int] = None  # Cooldown duration after close
    
    def is_expired(self) -> bool:
        """Check if position has exceeded max holding time"""
        if self.time_in_trade_limit_sec is None:
            return False
        opened = datetime.fromisoformat(self.opened_at)
        expires = opened + timedelta(seconds=self.time_in_trade_limit_sec)
        return datetime.utcnow() > expires
    
    def time_in_trade_seconds(self) -> int:
        """Get current time in trade"""
        opened = datetime.fromisoformat(self.opened_at)
        return int((datetime.utcnow() - opened).total_seconds())


@dataclass
class TrailingStopState:
    """State for trailing stop per position"""
    symbol: str
    direction: str
    highest_roi: float  # Highest ROI reached
    current_sl_price: float  # Current stop loss price
    last_updated: str  # ISO timestamp
    is_active: bool = False


class TradingState:
    """
    Unified trading state manager.
    
    This class provides thread-safe access to all trading state:
    - Order intents (for idempotency)
    - Cooldowns (per symbol+direction)
    - Position metadata
    - Trailing stop states
    """
    
    def __init__(self, filepath: str = TRADING_STATE_FILE):
        self.filepath = filepath
        self._ensure_file_exists()
    
    def _ensure_file_exists(self):
        """Ensure state file and parent directory exist"""
        parent = os.path.dirname(self.filepath)
        if parent:
            os.makedirs(parent, exist_ok=True)
        
        if not os.path.exists(self.filepath):
            self._save_raw_state({
                "version": "1.0.0",
                "last_updated": datetime.utcnow().isoformat(),
                "order_intents": {},
                "cooldowns": [],
                "position_metadata": {},
                "trailing_stops": {}
            })
    
    def _load_raw_state(self) -> dict:
        """Load raw state from file (thread-safe)"""
        with _state_lock:
            try:
                with open(self.filepath, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ Error loading trading state: {e}")
                return {
                    "version": "1.0.0",
                    "last_updated": datetime.utcnow().isoformat(),
                    "order_intents": {},
                    "cooldowns": [],
                    "position_metadata": {},
                    "trailing_stops": {}
                }
    
    def _save_raw_state(self, state: dict):
        """Save raw state to file (thread-safe)"""
        with _state_lock:
            try:
                state["last_updated"] = datetime.utcnow().isoformat()
                with open(self.filepath, 'w') as f:
                    json.dump(state, f, indent=2)
            except Exception as e:
                print(f"⚠️ Error saving trading state: {e}")
    
    # ===== ORDER INTENTS (Idempotency) =====
    
    def add_intent(self, intent: OrderIntent) -> bool:
        """Add a new order intent. Returns False if intent_id already exists."""
        state = self._load_raw_state()
        
        if intent.intent_id in state["order_intents"]:
            print(f"⚠️ Intent {intent.intent_id} already exists (idempotency)")
            return False
        
        state["order_intents"][intent.intent_id] = asdict(intent)
        self._save_raw_state(state)
        return True
    
    def get_intent(self, intent_id: str) -> Optional[OrderIntent]:
        """Get an order intent by ID"""
        state = self._load_raw_state()
        intent_data = state["order_intents"].get(intent_id)
        if intent_data:
            return OrderIntent(**intent_data)
        return None
    
    def update_intent_status(self, intent_id: str, status: OrderStatus, 
                            exchange_order_id: Optional[str] = None,
                            error_message: Optional[str] = None):
        """Update the status of an order intent"""
        state = self._load_raw_state()
        
        if intent_id not in state["order_intents"]:
            print(f"⚠️ Intent {intent_id} not found")
            return
        
        state["order_intents"][intent_id]["status"] = status.value
        
        if status == OrderStatus.EXECUTED:
            state["order_intents"][intent_id]["executed_at"] = datetime.utcnow().isoformat()
        
        if exchange_order_id:
            state["order_intents"][intent_id]["exchange_order_id"] = exchange_order_id
        
        if error_message:
            state["order_intents"][intent_id]["error_message"] = error_message
        
        self._save_raw_state(state)
    
    def cleanup_old_intents(self, days: int = 7):
        """Remove intents older than N days"""
        state = self._load_raw_state()
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        cleaned = {}
        for intent_id, intent_data in state["order_intents"].items():
            created = datetime.fromisoformat(intent_data["created_at"])
            if created > cutoff:
                cleaned[intent_id] = intent_data
        
        removed = len(state["order_intents"]) - len(cleaned)
        if removed > 0:
            print(f"🧹 Cleaned {removed} old intents")
            state["order_intents"] = cleaned
            self._save_raw_state(state)
    
    # ===== COOLDOWNS =====
    
    def add_cooldown(self, cooldown: Cooldown):
        """Add a cooldown entry"""
        state = self._load_raw_state()
        state["cooldowns"].append(asdict(cooldown))
        
        # Keep only last 100 cooldowns
        state["cooldowns"] = state["cooldowns"][-100:]
        
        self._save_raw_state(state)
        print(f"💾 Cooldown added: {cooldown.symbol} {cooldown.direction}")
    
    def get_active_cooldowns(self) -> List[Cooldown]:
        """Get all currently active cooldowns"""
        state = self._load_raw_state()
        active = []
        
        for cd_data in state["cooldowns"]:
            cd = Cooldown(**cd_data)
            if cd.is_active():
                active.append(cd)
        
        return active
    
    def is_in_cooldown(self, symbol: str, direction: str) -> bool:
        """Check if a symbol+direction is currently in cooldown"""
        for cd in self.get_active_cooldowns():
            if cd.symbol == symbol and cd.direction.lower() == direction.lower():
                return True
        return False
    
    def cleanup_expired_cooldowns(self):
        """Remove expired cooldowns from state"""
        state = self._load_raw_state()
        active = []
        
        for cd_data in state["cooldowns"]:
            cd = Cooldown(**cd_data)
            if cd.is_active():
                active.append(cd_data)
        
        removed = len(state["cooldowns"]) - len(active)
        if removed > 0:
            print(f"🧹 Cleaned {removed} expired cooldowns")
            state["cooldowns"] = active
            self._save_raw_state(state)
    
    # ===== POSITION METADATA =====
    
    def add_position(self, position: PositionMetadata):
        """Add metadata for an open position"""
        state = self._load_raw_state()
        key = f"{position.symbol}_{position.direction}"
        state["position_metadata"][key] = asdict(position)
        self._save_raw_state(state)
        print(f"📊 Position metadata added: {key}")
    
    def get_position(self, symbol: str, direction: str) -> Optional[PositionMetadata]:
        """Get position metadata"""
        state = self._load_raw_state()
        key = f"{symbol}_{direction}"
        pos_data = state["position_metadata"].get(key)
        if pos_data:
            return PositionMetadata(**pos_data)
        return None
    
    def remove_position(self, symbol: str, direction: str):
        """Remove position metadata (called on close)"""
        state = self._load_raw_state()
        key = f"{symbol}_{direction}"
        if key in state["position_metadata"]:
            del state["position_metadata"][key]
            self._save_raw_state(state)
            print(f"🗑️ Position metadata removed: {key}")
    
    def get_all_positions(self) -> List[PositionMetadata]:
        """Get all position metadata"""
        state = self._load_raw_state()
        positions = []
        for pos_data in state["position_metadata"].values():
            positions.append(PositionMetadata(**pos_data))
        return positions
    
    def get_expired_positions(self) -> List[PositionMetadata]:
        """Get positions that have exceeded their time_in_trade_limit"""
        expired = []
        for pos in self.get_all_positions():
            if pos.is_expired():
                expired.append(pos)
        return expired
    
    # ===== TRAILING STOPS =====
    
    def update_trailing_stop(self, trailing_stop: TrailingStopState):
        """Update trailing stop state for a position"""
        state = self._load_raw_state()
        key = f"{trailing_stop.symbol}_{trailing_stop.direction}"
        state["trailing_stops"][key] = asdict(trailing_stop)
        self._save_raw_state(state)
    
    def get_trailing_stop(self, symbol: str, direction: str) -> Optional[TrailingStopState]:
        """Get trailing stop state"""
        state = self._load_raw_state()
        key = f"{symbol}_{direction}"
        ts_data = state["trailing_stops"].get(key)
        if ts_data:
            return TrailingStopState(**ts_data)
        return None
    
    def remove_trailing_stop(self, symbol: str, direction: str):
        """Remove trailing stop state (called on close)"""
        state = self._load_raw_state()
        key = f"{symbol}_{direction}"
        if key in state["trailing_stops"]:
            del state["trailing_stops"][key]
            self._save_raw_state(state)


# Singleton instance
_trading_state_instance = None

def get_trading_state() -> TradingState:
    """Get singleton instance of TradingState"""
    global _trading_state_instance
    if _trading_state_instance is None:
        _trading_state_instance = TradingState()
    return _trading_state_instance
