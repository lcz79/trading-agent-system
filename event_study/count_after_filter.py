import pandas as pd

df = pd.read_csv("/data/event_study/events_3pct_intraday_1y.cleaned.csv")
df["t0"] = pd.to_datetime(df["t0"], utc=True)
df["day"] = df["t0"].dt.date

cfg = {
  "BTC/USDT:USDT": {"adx1h": 20, "atr15m": 0.27},
  "ETH/USDT:USDT": {"adx1h": 20, "atr15m": 0.43},
  "SOL/USDT:USDT": {"adx1h": 20, "atr15m": 0.50},
}

for sym, th in cfg.items():
    d = df[df["symbol"]==sym].copy()
    base_n = len(d)
    d2 = d[(d["1h_adx14"]>=th["adx1h"]) & (d["15m_atrpct14"]>=th["atr15m"])]

    per_day = d2.groupby("day").size()
    avg = float(per_day.mean()) if len(per_day) else 0.0
    p50 = float(per_day.quantile(0.5)) if len(per_day) else 0.0
    p75 = float(per_day.quantile(0.75)) if len(per_day) else 0.0

    print(f"\n== {sym} ==")
    print("rows total events:", base_n)
    print("rows after filter :", len(d2))
    print(f"events/day avg={avg:.2f} p50={p50:.2f} p75={p75:.2f}")

    print(f"mfe mean before={d["mfe"].mean():.4f} after={d2["mfe"].mean():.4f}")
    print(f"mae mean before={d["mae"].mean():.4f} after={d2["mae"].mean():.4f}")
