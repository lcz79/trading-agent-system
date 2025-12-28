"""
FASE 2 Scalping Optimizations - Centralized Configuration

This module centralizes all configuration parameters for FASE 2 optimizations:
- Risk-based position sizing
- Volatility filtering
- Dynamic trailing stops
- Time-based exits with ADX awareness
- Spread & slippage control
- Market regime detection
- Telemetry parameters

All parameters can be overridden via environment variables or per-symbol configuration.
"""

import os
from typing import Dict, Optional
from dataclasses import dataclass, field


@dataclass
class RiskConfig:
    """Risk management configuration"""
    # Equity risk per trade (default 0.30% = 0.003)
    risk_pct: float = float(os.getenv("RISK_PCT", "0.003"))
    min_risk_pct: float = 0.0025  # 0.25%
    max_risk_pct: float = 0.006   # 0.60%
    
    # Per-symbol overrides (format: "BTCUSDT:0.0025,ETHUSDT:0.003")
    symbol_risk_overrides: Dict[str, float] = field(default_factory=dict)
    
    def get_risk_pct(self, symbol: str) -> float:
        """Get risk percentage for a specific symbol"""
        return self.symbol_risk_overrides.get(symbol, self.risk_pct)


@dataclass
class VolatilityFilterConfig:
    """Volatility filter (anti-chop) configuration"""
    # Minimum volatility threshold (default 0.0025 = 0.25%)
    min_volatility_pct: float = float(os.getenv("MIN_VOLATILITY_PCT", "0.0025"))
    
    # ATR period for volatility calculation
    atr_period: int = 14
    
    # Per-symbol overrides
    symbol_volatility_overrides: Dict[str, float] = field(default_factory=dict)
    
    def get_min_volatility(self, symbol: str) -> float:
        """Get minimum volatility for a specific symbol"""
        return self.symbol_volatility_overrides.get(symbol, self.min_volatility_pct)


@dataclass
class TrailingStopConfig:
    """Dynamic trailing stop configuration (ATR-based)"""
    # Base ATR multiplier for trailing distance
    atr_multiplier_base: float = float(os.getenv("TRAILING_ATR_MULTIPLIER", "1.2"))
    
    # ATR multiplier in TREND mode (more lenient)
    atr_multiplier_trend: float = float(os.getenv("TRAILING_ATR_MULTIPLIER_TREND", "1.5"))
    
    # ATR multiplier in RANGE mode (tighter)
    atr_multiplier_range: float = float(os.getenv("TRAILING_ATR_MULTIPLIER_RANGE", "1.0"))
    
    # Minimum ATR value to avoid division issues (in price units)
    min_atr_clamp: float = float(os.getenv("MIN_ATR_CLAMP", "0.0001"))
    
    # Minimum trailing distance percentage (0.5%)
    min_trailing_distance_pct: float = float(os.getenv("MIN_TRAILING_DISTANCE_PCT", "0.005"))
    
    # Maximum trailing distance percentage (8%)
    max_trailing_distance_pct: float = float(os.getenv("MAX_TRAILING_DISTANCE_PCT", "0.08"))


@dataclass
class TimeExitConfig:
    """Time-based exit configuration with ADX awareness"""
    # Base time-exit in seconds (default 40 minutes = 2400 seconds)
    base_time_exit_sec: int = int(os.getenv("BASE_TIME_EXIT_SEC", "2400"))
    
    # Extension time if ADX indicates strong trend (default +20 minutes = 1200 seconds)
    extension_time_sec: int = int(os.getenv("TIME_EXIT_EXTENSION_SEC", "1200"))
    
    # ADX threshold to trigger extension (default 25)
    adx_threshold: float = float(os.getenv("TIME_EXIT_ADX_THRESHOLD", "25.0"))
    
    # ADX period for calculation
    adx_period: int = 14
    
    # Per-symbol overrides for base time exit
    symbol_time_exit_overrides: Dict[str, int] = field(default_factory=dict)
    
    def get_base_time_exit(self, symbol: str) -> int:
        """Get base time exit for a specific symbol"""
        return self.symbol_time_exit_overrides.get(symbol, self.base_time_exit_sec)


@dataclass
class SpreadSlippageConfig:
    """Spread and slippage control configuration"""
    # Maximum acceptable spread (default 0.0008 = 0.08%)
    max_spread_pct: float = float(os.getenv("MAX_SPREAD_PCT", "0.0008"))
    
    # Orderbook depth to fetch for spread calculation
    orderbook_depth: int = 10
    
    # Enable pre-trade spread check
    enable_spread_check: bool = os.getenv("ENABLE_SPREAD_CHECK", "true").lower() == "true"
    
    # Enable post-fill slippage logging
    enable_slippage_logging: bool = os.getenv("ENABLE_SLIPPAGE_LOGGING", "true").lower() == "true"


@dataclass
class RegimeDetectionConfig:
    """Market regime detection configuration (TREND vs RANGE)"""
    # Trend strength threshold (default 0.005 = 0.5%)
    # trend_strength = abs((EMA20 - EMA200) / EMA200)
    trend_threshold: float = float(os.getenv("REGIME_TREND_THRESHOLD", "0.005"))
    
    # EMA periods for regime detection
    ema_short_period: int = 20
    ema_long_period: int = 200
    
    # Regime-specific parameter adjustments
    # In TREND mode: more lenient trailing and TP
    trend_mode_tp_multiplier: float = 1.5
    trend_mode_trailing_multiplier: float = 1.5
    
    # In RANGE mode: tighter trailing and TP
    range_mode_tp_multiplier: float = 1.0
    range_mode_trailing_multiplier: float = 1.0


@dataclass
class TimestampAlignmentConfig:
    """Timestamp alignment configuration for agent synchronization"""
    # Maximum allowed timestamp drift between agents (default 30 seconds)
    max_timestamp_drift_sec: int = int(os.getenv("MAX_TIMESTAMP_DRIFT_SEC", "30"))
    
    # Enable timestamp alignment check
    enable_alignment_check: bool = os.getenv("ENABLE_TIMESTAMP_ALIGNMENT", "true").lower() == "true"


@dataclass
class ReconciliationConfig:
    """Position/order reconciliation configuration"""
    # Enable reconciliation before critical actions
    enable_reconciliation: bool = os.getenv("ENABLE_RECONCILIATION", "true").lower() == "true"
    
    # Reconciliation check interval (seconds)
    reconciliation_interval_sec: int = int(os.getenv("RECONCILIATION_INTERVAL_SEC", "60"))


@dataclass
class TelemetryConfig:
    """Telemetry and logging configuration"""
    # Enable comprehensive trade telemetry
    enable_telemetry: bool = os.getenv("ENABLE_TELEMETRY", "true").lower() == "true"
    
    # Telemetry file path (JSONL format)
    telemetry_file: str = os.getenv("TELEMETRY_FILE", "/data/trade_telemetry.jsonl")
    
    # Maximum telemetry file size in MB (rotation trigger)
    max_file_size_mb: int = int(os.getenv("TELEMETRY_MAX_SIZE_MB", "50"))
    
    # Number of rotated files to keep
    max_rotated_files: int = int(os.getenv("TELEMETRY_MAX_ROTATED_FILES", "5"))


@dataclass
class BaselineParametersConfig:
    """Baseline trading parameters (FASE 2 defaults)"""
    # Stop Loss: 1.2 × ATR(14)
    sl_atr_multiplier: float = float(os.getenv("SL_ATR_MULTIPLIER", "1.2"))
    
    # Take Profit: 2.4 × ATR(14)
    tp_atr_multiplier: float = float(os.getenv("TP_ATR_MULTIPLIER", "2.4"))
    
    # Trailing activation: +1.2 × ATR
    trailing_activation_atr_multiplier: float = float(os.getenv("TRAILING_ACTIVATION_ATR_MULTIPLIER", "1.2"))
    
    # Cooldown per symbol (default 15 minutes = 900 seconds)
    cooldown_sec: int = int(os.getenv("DEFAULT_COOLDOWN_SEC", "900"))
    
    # Maximum daily drawdown threshold (default -7%)
    max_daily_drawdown_pct: float = float(os.getenv("MAX_DAILY_DRAWDOWN_PCT", "-0.07"))


@dataclass
class FASE2Config:
    """Master configuration for FASE 2 optimizations"""
    risk: RiskConfig = field(default_factory=RiskConfig)
    volatility_filter: VolatilityFilterConfig = field(default_factory=VolatilityFilterConfig)
    trailing_stop: TrailingStopConfig = field(default_factory=TrailingStopConfig)
    time_exit: TimeExitConfig = field(default_factory=TimeExitConfig)
    spread_slippage: SpreadSlippageConfig = field(default_factory=SpreadSlippageConfig)
    regime: RegimeDetectionConfig = field(default_factory=RegimeDetectionConfig)
    timestamp_alignment: TimestampAlignmentConfig = field(default_factory=TimestampAlignmentConfig)
    reconciliation: ReconciliationConfig = field(default_factory=ReconciliationConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    baseline: BaselineParametersConfig = field(default_factory=BaselineParametersConfig)
    
    @classmethod
    def load_from_env(cls) -> 'FASE2Config':
        """Load configuration from environment variables"""
        config = cls()
        
        # Parse per-symbol risk overrides
        risk_overrides_str = os.getenv("SYMBOL_RISK_OVERRIDES", "")
        if risk_overrides_str:
            for pair in risk_overrides_str.split(","):
                if ":" in pair:
                    symbol, risk_str = pair.split(":", 1)
                    try:
                        config.risk.symbol_risk_overrides[symbol.strip()] = float(risk_str.strip())
                    except ValueError:
                        pass
        
        # Parse per-symbol volatility overrides
        vol_overrides_str = os.getenv("SYMBOL_VOLATILITY_OVERRIDES", "")
        if vol_overrides_str:
            for pair in vol_overrides_str.split(","):
                if ":" in pair:
                    symbol, vol_str = pair.split(":", 1)
                    try:
                        config.volatility_filter.symbol_volatility_overrides[symbol.strip()] = float(vol_str.strip())
                    except ValueError:
                        pass
        
        # Parse per-symbol time exit overrides
        time_overrides_str = os.getenv("SYMBOL_TIME_EXIT_OVERRIDES", "")
        if time_overrides_str:
            for pair in time_overrides_str.split(","):
                if ":" in pair:
                    symbol, time_str = pair.split(":", 1)
                    try:
                        config.time_exit.symbol_time_exit_overrides[symbol.strip()] = int(time_str.strip())
                    except ValueError:
                        pass
        
        return config


# Global configuration instance
_config: Optional[FASE2Config] = None


def get_fase2_config() -> FASE2Config:
    """Get the global FASE2 configuration instance"""
    global _config
    if _config is None:
        _config = FASE2Config.load_from_env()
    return _config


def reload_fase2_config() -> FASE2Config:
    """Force reload configuration from environment"""
    global _config
    _config = FASE2Config.load_from_env()
    return _config
