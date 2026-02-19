import os, time
from datetime import datetime, timedelta, timezone
import pandas as pd
import ccxt

from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.volatility import AverageTrueRange

SYMBOLS = ["BTC/USDT:USDT","ETH/USDT:USDT","SOL/USDT:USDT"]
TIMEFRAMES = ["5m","15m","1h","4h"]
BASE_TF = "15m"
HORIZONS_HOURS = [2,4,6,12]
THRESH_PCT = 0.03
DAYS = 365

OUTDIR="/data/event_study"
OHLCVDIR=f"{OUTDIR}/ohlcv"
os.makedirs(OUTDIR, exist_ok=True)
os.makedirs(OHLCVDIR, exist_ok=True)

def safe_sym(s: str) -> str:
    return s.replace("/", "_").replace(":", "_")

def utc_ms(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp()*1000)

def make_ex():
    return ccxt.bybit({"enableRateLimit": True, "options":{"defaultType":"swap"}})

def fetch_all(ex, symbol, tf, since_ms, until_ms):
    all_rows=[]
    since=since_ms
    limit=1000
    while since < until_ms:
        try:
            rows=ex.fetch_ohlcv(symbol, timeframe=tf, since=since, limit=limit, params={"category":"linear"})
        except Exception as err:
            print(f"[fetch] {symbol} {tf} err={err} -> sleep 2s")
            time.sleep(2)
            continue
        if not rows:
            break
        all_rows.extend(rows)
        since = rows[-1][0] + 1
        time.sleep(ex.rateLimit/1000.0)

    df=pd.DataFrame(all_rows, columns=["ts","open","high","low","close","volume"]).drop_duplicates("ts").sort_values("ts")
    df["datetime"]=pd.to_datetime(df["ts"], unit="ms", utc=True)
    df=df.set_index("datetime")
    for c in ["open","high","low","close","volume","ts"]:
        df[c]=pd.to_numeric(df[c], errors="coerce")
    return df

def add_ind(df):
    d=df.copy()
    close=d["close"]
    high=d["high"]
    low=d["low"]

    d["rsi14"]=RSIIndicator(close, window=14).rsi()
    d["ema20"]=EMAIndicator(close, window=20).ema_indicator()
    d["ema50"]=EMAIndicator(close, window=50).ema_indicator()

    macd=MACD(close, window_slow=26, window_fast=12, window_sign=9)
    d["macd"]=macd.macd()
    d["macdh"]=macd.macd_diff()
    d["macds"]=macd.macd_signal()

    atr=AverageTrueRange(high=high, low=low, close=close, window=14)
    d["atr14"]=atr.average_true_range()
    d["atrpct14"]=(d["atr14"]/d["close"])*100.0

    adx=ADXIndicator(high=high, low=low, close=close, window=14)
    d["adx14"]=adx.adx()
    d["dmp14"]=adx.adx_pos()
    d["dmn14"]=adx.adx_neg()

    vol=d["volume"]
    d["volz100"]=(vol-vol.rolling(100).mean())/(vol.rolling(100).std(ddof=0))

    d["ema20_slope5"]=d["ema20"].diff(5)
    d["rsi_slope5"]=d["rsi14"].diff(5)
    return d

def compute_events(df15):
    d=df15.copy()
    t = d.index.to_list()
    closes=d["close"].to_numpy()
    highs=d["high"].to_numpy()
    lows=d["low"].to_numpy()

    bph = 4  # 15m bars per hour
    rows=[]
    for i in range(len(d)):
        c0=closes[i]
        if not (c0 and c0>0):
            continue
        best_long=None
        best_short=None
        for h in HORIZONS_HOURS:
            n=h*bph
            j1=min(i+n, len(d)-1)
            if j1<=i:
                continue
            maxh=float(highs[i+1:j1+1].max())
            minl=float(lows[i+1:j1+1].min())

            long_mfe=(maxh/c0)-1.0
            long_mae=(minl/c0)-1.0
            short_mfe=(c0/minl)-1.0
            short_mae=(c0/maxh)-1.0

            if long_mfe>=THRESH_PCT and (best_long is None or long_mfe>best_long["mfe"]):
                best_long={"h":h,"mfe":long_mfe,"mae":long_mae}
            if short_mfe>=THRESH_PCT and (best_short is None or short_mfe>best_short["mfe"]):
                best_short={"h":h,"mfe":short_mfe,"mae":short_mae}

        if best_long:
            rows.append({"t0": t[i], "direction":"long", "best_h":best_long["h"], "mfe":best_long["mfe"], "mae":best_long["mae"]})
        if best_short:
            rows.append({"t0": t[i], "direction":"short", "best_h":best_short["h"], "mfe":best_short["mfe"], "mae":best_short["mae"]})
    return pd.DataFrame(rows)

def snap(df, ts):
    if ts in df.index:
        r=df.loc[ts]
    else:
        loc=df.index.get_indexer([ts], method="pad")
        if loc[0] < 0:
            return None
        r=df.iloc[loc[0]]
    cols=["rsi14","ema20","ema50","macd","macdh","macds","atr14","atrpct14","adx14","dmp14","dmn14","volz100","ema20_slope5","rsi_slope5","close"]
    out={}
    for c in cols:
        out[c]=float(r[c]) if (c in r and pd.notna(r[c])) else None
    return out

def main():
    ex=make_ex()
    until=datetime.now(timezone.utc)
    since=until - timedelta(days=DAYS)
    since_ms=utc_ms(since); until_ms=utc_ms(until)

    all_events=[]
    for sym in SYMBOLS:
        print(f"== {sym} ==")
        dfs={}
        for tf in TIMEFRAMES:
            path=f"{OHLCVDIR}/{safe_sym(sym)}_{tf}.csv"
            if os.path.exists(path):
                df=pd.read_csv(path)
                df["datetime"]=pd.to_datetime(df["datetime"], utc=True)
                df=df.set_index("datetime")
                for c in ["open","high","low","close","volume","ts"]:
                    df[c]=pd.to_numeric(df[c], errors="coerce")
            else:
                df=fetch_all(ex, sym, tf, since_ms, until_ms)
                df.reset_index().to_csv(path, index=False)

            dfs[tf]=add_ind(df)

        base=dfs[BASE_TF].dropna(subset=["close"])
        ev=compute_events(base)
        if ev.empty:
            continue

        enriched=[]
        for _,row in ev.iterrows():
            t0=pd.to_datetime(row["t0"], utc=True)
            rec={"symbol":sym, "t0":t0, "direction":row["direction"], "best_h":int(row["best_h"]),
                 "mfe":float(row["mfe"]), "mae":float(row["mae"]), "threshold_pct":THRESH_PCT}
            for tf in TIMEFRAMES:
                s=snap(dfs[tf], t0)
                if s is None:
                    continue
                for k,v in s.items():
                    rec[f"{tf}_{k}"]=v
            enriched.append(rec)

        out=pd.DataFrame(enriched).sort_values(["symbol","t0","direction"])
        all_events.append(out)

    if not all_events:
        raise SystemExit("No events found")

    final=pd.concat(all_events, ignore_index=True)
    outpath=f"{OUTDIR}/events_{int(THRESH_PCT*100)}pct_intraday_1y.csv"
    final.to_csv(outpath, index=False)
    print("WROTE:", outpath)
    print("ROWS:", len(final))
    print(final.head(5).to_string(index=False))

if __name__=="__main__":
    main()
