"""
FASE 2 Telemetry Module - Comprehensive Trade Logging

This module provides structured logging for all trades with:
- Per-trade metrics: entry, exit, PnL, fees, slippage
- Market context: spread, volatility, regime
- Exit reasons: SL, TP, time_exit, manual, etc.
- JSONL format with rotation

All logging errors are caught and logged without crashing the main loop.
"""

import json
import os
from datetime import datetime
from typing import Dict, Any, Optional
from threading import Lock
from dataclasses import dataclass, asdict


# Thread-safe lock for file operations
_telemetry_lock = Lock()


@dataclass
class TradeRecord:
    """Structured trade record for telemetry"""
    timestamp: str
    symbol: str
    side: str  # long or short
    entry_price: float
    exit_price: Optional[float]
    entry_time: str
    exit_time: Optional[str]
    
    # PnL metrics
    pnl_pct_gross: float  # Gross PnL without fees
    pnl_pct_net: float    # Net PnL after fees
    pnl_dollars: float
    
    # Fees and costs
    fees_dollars: float
    fees_pct: float
    
    # Slippage metrics
    slippage_pct: Optional[float] = None
    expected_entry_price: Optional[float] = None
    expected_exit_price: Optional[float] = None
    
    # Market context at entry
    spread_pct_entry: Optional[float] = None
    volatility_atr_pct: Optional[float] = None
    atr_value: Optional[float] = None
    
    # Position parameters
    leverage: float = 1.0
    size: float = 0.0
    size_pct: float = 0.0
    
    # Regime and market state
    mode: str = "UNKNOWN"  # TREND, RANGE, UNKNOWN
    trend_strength: Optional[float] = None
    adx: Optional[float] = None
    
    # Exit reason
    reason_exit: str = "unknown"  # sl, tp, time_exit_flat, time_exit_trend, manual, reconcile_missing, etc.
    
    # Additional metadata
    intent_id: Optional[str] = None
    duration_sec: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return asdict(self)


class TelemetryLogger:
    """Thread-safe telemetry logger with rotation support"""
    
    def __init__(self, filepath: str, max_size_mb: int = 50, max_rotated_files: int = 5):
        self.filepath = filepath
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.max_rotated_files = max_rotated_files
        self._ensure_parent_dir()
    
    def _ensure_parent_dir(self):
        """Ensure parent directory exists"""
        parent = os.path.dirname(self.filepath)
        if parent:
            os.makedirs(parent, exist_ok=True)
    
    def _check_rotation(self):
        """Check if rotation is needed and perform rotation"""
        try:
            if os.path.exists(self.filepath):
                size = os.path.getsize(self.filepath)
                if size >= self.max_size_bytes:
                    self._rotate()
        except Exception as e:
            print(f"⚠️ Telemetry rotation check failed: {e}")
    
    def _rotate(self):
        """Rotate telemetry files"""
        try:
            # Delete oldest rotated file if max reached
            oldest = f"{self.filepath}.{self.max_rotated_files}"
            if os.path.exists(oldest):
                os.remove(oldest)
            
            # Shift existing rotated files
            for i in range(self.max_rotated_files - 1, 0, -1):
                old_file = f"{self.filepath}.{i}"
                new_file = f"{self.filepath}.{i + 1}"
                if os.path.exists(old_file):
                    os.rename(old_file, new_file)
            
            # Rotate current file
            if os.path.exists(self.filepath):
                os.rename(self.filepath, f"{self.filepath}.1")
            
            print(f"📊 Telemetry file rotated: {self.filepath}")
        except Exception as e:
            print(f"⚠️ Telemetry rotation failed: {e}")
    
    def log_trade(self, record: TradeRecord):
        """Log a trade record to JSONL file (thread-safe)"""
        with _telemetry_lock:
            try:
                # Check rotation before writing
                self._check_rotation()
                
                # Append to JSONL
                with open(self.filepath, 'a', encoding='utf-8') as f:
                    json.dump(record.to_dict(), f, ensure_ascii=False)
                    f.write('\n')
                
                # Optional: print summary for monitoring
                print(
                    f"📊 TELEMETRY: {record.symbol} {record.side} "
                    f"PnL={record.pnl_pct_net:.2f}% exit={record.reason_exit} mode={record.mode}"
                )
            except Exception as e:
                # Never crash on logging errors
                print(f"⚠️ Telemetry logging failed: {e}")
    
    def read_recent_trades(self, limit: int = 100) -> list:
        """Read recent trades from telemetry file"""
        trades = []
        try:
            if os.path.exists(self.filepath):
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            trades.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
                
                # Return last N trades
                return trades[-limit:]
        except Exception as e:
            print(f"⚠️ Failed to read telemetry: {e}")
        
        return trades


# Global telemetry logger instance
_telemetry_logger: Optional[TelemetryLogger] = None


def get_telemetry_logger(
    filepath: str = "/data/trade_telemetry.jsonl",
    max_size_mb: int = 50,
    max_rotated_files: int = 5
) -> TelemetryLogger:
    """Get the global telemetry logger instance"""
    global _telemetry_logger
    if _telemetry_logger is None:
        _telemetry_logger = TelemetryLogger(filepath, max_size_mb, max_rotated_files)
    return _telemetry_logger


def log_trade_telemetry(
    symbol: str,
    side: str,
    entry_price: float,
    exit_price: Optional[float],
    entry_time: str,
    exit_time: Optional[str],
    pnl_pct_gross: float,
    pnl_pct_net: float,
    pnl_dollars: float,
    fees_dollars: float,
    fees_pct: float,
    reason_exit: str,
    leverage: float = 1.0,
    size: float = 0.0,
    size_pct: float = 0.0,
    mode: str = "UNKNOWN",
    slippage_pct: Optional[float] = None,
    spread_pct_entry: Optional[float] = None,
    volatility_atr_pct: Optional[float] = None,
    atr_value: Optional[float] = None,
    trend_strength: Optional[float] = None,
    adx: Optional[float] = None,
    intent_id: Optional[str] = None,
    duration_sec: Optional[int] = None,
    expected_entry_price: Optional[float] = None,
    expected_exit_price: Optional[float] = None,
    enabled: bool = True
):
    """
    Convenience function to log a trade with telemetry.
    
    This function never raises exceptions - all errors are caught and logged.
    """
    if not enabled:
        return
    
    try:
        record = TradeRecord(
            timestamp=datetime.utcnow().isoformat(),
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            entry_time=entry_time,
            exit_time=exit_time,
            pnl_pct_gross=pnl_pct_gross,
            pnl_pct_net=pnl_pct_net,
            pnl_dollars=pnl_dollars,
            fees_dollars=fees_dollars,
            fees_pct=fees_pct,
            slippage_pct=slippage_pct,
            expected_entry_price=expected_entry_price,
            expected_exit_price=expected_exit_price,
            spread_pct_entry=spread_pct_entry,
            volatility_atr_pct=volatility_atr_pct,
            atr_value=atr_value,
            leverage=leverage,
            size=size,
            size_pct=size_pct,
            mode=mode,
            trend_strength=trend_strength,
            adx=adx,
            reason_exit=reason_exit,
            intent_id=intent_id,
            duration_sec=duration_sec
        )
        
        logger = get_telemetry_logger()
        logger.log_trade(record)
    except Exception as e:
        # Never crash on telemetry errors
        print(f"⚠️ Telemetry error: {e}")
