import pandas as pd

df = pd.read_csv("/data/event_study/events_3pct_intraday_1y.cleaned.csv")

cols = [
  "15m_rsi14","15m_adx14","15m_atrpct14","15m_ema20_slope5","15m_rsi_slope5",
  "1h_rsi14","1h_adx14","1h_atrpct14","1h_ema20_slope5","1h_rsi_slope5",
  "4h_rsi14","4h_adx14","4h_atrpct14"
]

def summary(g):
    out={}
    for c in cols:
        s=g[c].dropna()
        out[c]={
            "mean": float(s.mean()),
            "p25": float(s.quantile(0.25)),
            "p50": float(s.quantile(0.50)),
            "p75": float(s.quantile(0.75)),
        }
    return out

for sym in sorted(df["symbol"].unique()):
    d = df[df["symbol"]==sym]
    print(f"\n== {sym} rows {len(d)} ==")
    for direction in ["long","short"]:
        g = d[d["direction"]==direction]
        print(f"-- {direction} rows {len(g)}")
        rep = summary(g)
        for k in ["15m_rsi14","15m_adx14","15m_atrpct14","1h_adx14","1h_atrpct14","4h_adx14","4h_atrpct14"]:
            v = rep[k]
            print(f"  {k}: mean={v['mean']:.2f} p25={v['p25']:.2f} p50={v['p50']:.2f} p75={v['p75']:.2f}")
