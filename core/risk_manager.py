import json, math
class RiskManager:
    def __init__(self, cfg_path="config/risk_parameters.json"):
        self.cfg = json.load(open(cfg_path, "r"))
    def position_size(self, equity: float, entry: float, stop: float) -> float:
        risk_money = equity * self.cfg["risk_frac_per_trade"]
        risk_per_unit = abs(entry - stop)
        if risk_per_unit <= 1e-12: return 0.0
        return risk_money / risk_per_unit
    def can_open_new_symbol(self, exposure_symbols: int) -> bool:
        return exposure_symbols < self.cfg["max_concurrent_symbols"]