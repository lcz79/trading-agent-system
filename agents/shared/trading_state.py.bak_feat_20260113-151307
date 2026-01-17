import os
import json
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field, asdict
from enum import Enum

TRADING_STATE_FILE = os.getenv("TRADING_STATE_FILE", "/data/trading_state.json")

class OrderStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"

@dataclass
class OrderIntent:
    intent_id: str
    symbol: str
    side: str
    leverage: float
    size_pct: float
    action: Optional[str] = None
    status: OrderStatus = OrderStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    executed_at: Optional[str] = None
    error_message: Optional[str] = None
    exchange_order_id: Optional[str] = None
    tp_pct: Optional[float] = None
    sl_pct: Optional[float] = None
    time_in_trade_limit_sec:  Optional[int] = None
    cooldown_sec: Optional[int] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d['status'] = self.status.value if isinstance(self.status, OrderStatus) else self.status
        return d

    @classmethod
    def from_dict(cls, data: dict) -> 'OrderIntent': 
        data = data.copy()
        if 'status' in data:
            data['status'] = OrderStatus(data['status']) if isinstance(data['status'], str) else data['status']
        # Remove unknown fields
        valid_fields = {'intent_id', 'symbol', 'side', 'leverage', 'size_pct', 'action', 'status',
                       'created_at', 'executed_at', 'error_message', 'exchange_order_id',
                       'tp_pct', 'sl_pct', 'time_in_trade_limit_sec', 'cooldown_sec'}
        data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**data)

@dataclass
class PositionMetadata:
    symbol:  str
    side: str
    entry_price: float
    size:  float
    leverage: float
    opened_at: str = field(default_factory=lambda: datetime.now().isoformat())
    tp_pct: Optional[float] = None
    sl_pct: Optional[float] = None
    time_in_trade_limit_sec: Optional[int] = None
    cooldown_sec: Optional[int] = None
    intent_id: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data:  dict) -> 'PositionMetadata':
        valid_fields = {'symbol', 'side', 'entry_price', 'size', 'leverage', 'opened_at',
                       'tp_pct', 'sl_pct', 'time_in_trade_limit_sec', 'cooldown_sec', 'intent_id'}
        data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**data)

    def is_expired(self) -> bool:
        if not self.time_in_trade_limit_sec: 
            return False
        opened = datetime.fromisoformat(self.opened_at)
        return datetime.now() > opened + timedelta(seconds=self.time_in_trade_limit_sec)

@dataclass
class Cooldown:
    def __init__(self, symbol: str, side: str, expires_at: str, reason: str = "position_closed"):
        self.symbol = symbol
        self.side = side
        self.expires_at = expires_at
        self.reason = reason
    def __init__(self, symbol: str, side: str, expires_at: str, reason: str = "position_closed"):
        self.symbol = symbol
        self.side = side
        self.expires_at = expires_at
        self.reason = reason
    symbol: str
    side: str
    expires_at: str
    reason: str = "position_closed"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'Cooldown':
        return cls(**data)

    def is_expired(self) -> bool:
        return datetime.now() > datetime.fromisoformat(self.expires_at)

class TradingState: 
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None: 
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._file_lock = threading.Lock()
        self._state = self._load_state()
        self._initialized = True
    def _default_state(self) -> dict:
        """Default/required schema for the trading state file."""
        return {
            "version": "1.0.0",
            "last_updated": datetime.utcnow().isoformat(),
            "order_intents": {},
            "cooldowns": [],
            "position_metadata": {},
            "trailing_stops": {}
        }

    def _normalize_state(self, state: Any) -> dict:
        """Backward-compatible normalization of the raw JSON state."""
        defaults = self._default_state()
        if not isinstance(state, dict):
            return defaults

        for k, v in defaults.items():
            if k not in state:
                state[k] = v

        if not isinstance(state.get("order_intents"), dict):
            state["order_intents"] = {}
        if not isinstance(state.get("position_metadata"), dict):
            state["position_metadata"] = {}
        if not isinstance(state.get("trailing_stops"), dict):
            state["trailing_stops"] = {}
        if not isinstance(state.get("cooldowns"), list):
            state["cooldowns"] = []

        return state


    def _load_state(self) -> dict:
        try: 
            if os.path.exists(TRADING_STATE_FILE):
                with open(TRADING_STATE_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"⚠️ Error loading trading state: {e}")
        return {"intents": {}, "positions": {}, "cooldowns": [], "trailing_stops": {}}

    def _save_state(self):
        with self._file_lock:
            try:
                os.makedirs(os.path.dirname(TRADING_STATE_FILE), exist_ok=True)
                with open(TRADING_STATE_FILE, 'w') as f:
                    json.dump(self._state, f, indent=2)
            except Exception as e:
                print(f"⚠️ Error saving trading state: {e}")

    # --- Intent Management ---
    def add_intent(self, intent: OrderIntent):
        self._state["intents"][intent.intent_id] = intent.to_dict()
        self._save_state()

    def get_intent(self, intent_id:  str) -> Optional[OrderIntent]:
        data = self._state["intents"].get(intent_id)
        return OrderIntent.from_dict(data) if data else None

    def update_intent_status(self, intent_id: str, status: OrderStatus, 
                            error_message: Optional[str] = None,
                            exchange_order_id: Optional[str] = None):
        if intent_id in self._state["intents"]:
            self._state["intents"][intent_id]["status"] = status.value
            if status == OrderStatus.EXECUTED:
                self._state["intents"][intent_id]["executed_at"] = datetime.now().isoformat()
            if error_message:
                self._state["intents"][intent_id]["error_message"] = error_message
            if exchange_order_id:
                self._state["intents"][intent_id]["exchange_order_id"] = exchange_order_id
            self._save_state()

    def cleanup_old_intents(self, days: float = 1.0):
        cutoff = datetime.now() - timedelta(days=days)
        to_remove = []
        for intent_id, data in self._state["intents"].items():
            created = datetime.fromisoformat(data.get("created_at", datetime.now().isoformat()))
            if created < cutoff: 
                to_remove.append(intent_id)
        for intent_id in to_remove:
            del self._state["intents"][intent_id]
        if to_remove:
            self._save_state()

    # --- Position Management ---
    def add_position(self, position: PositionMetadata):
        key = f"{position.symbol}_{position.side}"
        self._state["positions"][key] = position.to_dict()
        self._save_state()

    def get_position(self, symbol: str, side: str) -> Optional[PositionMetadata]:
        key = f"{symbol}_{side}"
        data = self._state["positions"].get(key)
        return PositionMetadata.from_dict(data) if data else None

    def remove_position(self, symbol: str, side: str):
        key = f"{symbol}_{side}"
        if key in self._state["positions"]:
            del self._state["positions"][key]
            self._save_state()

    def get_expired_positions(self) -> List[PositionMetadata]: 
        expired = []
        for key, data in self._state["positions"].items():
            pos = PositionMetadata.from_dict(data)
            if pos.is_expired():
                expired.append(pos)
        return expired

    # --- Cooldown Management ---
    def add_cooldown(self, cooldown: Cooldown):
        self._state["cooldowns"].append(cooldown.to_dict())
        self._save_state()

    def is_in_cooldown(self, symbol:  str, side: str) -> bool:
        for cd_data in self._state["cooldowns"]: 
            cd = Cooldown.from_dict(cd_data)
            if cd.symbol == symbol and cd.side == side:
                if not cd.is_expired():
                    return True
        return False

    def cleanup_expired_cooldowns(self):
        valid = []
        for cd_data in self._state["cooldowns"]:
            cd = Cooldown.from_dict(cd_data)
            if not cd.is_expired():
                valid.append(cd_data)
        if len(valid) != len(self._state["cooldowns"]):
            self._state["cooldowns"] = valid
            self._save_state()

    # --- Trailing Stop Management ---
    def set_trailing_stop(self, symbol: str, side: str, data: dict):
        key = f"{symbol}_{side}"
        self._state["trailing_stops"][key] = data
        self._save_state()

    def get_trailing_stop(self, symbol: str, side: str) -> Optional[dict]:
        key = f"{symbol}_{side}"
        return self._state["trailing_stops"].get(key)

    def remove_trailing_stop(self, symbol: str, side: str):
        key = f"{symbol}_{side}"
        if key in self._state["trailing_stops"]: 
            del self._state["trailing_stops"][key]
            self._save_state()

def get_trading_state() -> TradingState:
    return TradingState()
