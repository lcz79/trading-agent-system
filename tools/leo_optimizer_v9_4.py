# =============================================================================
# MITRAGLIERE A.I. — LEO OPTIMIZER v9.4 "Robustness Update"
# Versione finale con bugfix per la gestione di dati storici scarsi.
# =============================================================================

import argparse, json, logging, math, os, time, warnings
from dataclasses import dataclass, asdict
from itertools import product
from multiprocessing import Pool, cpu_count
from typing import Dict, List, Tuple, Any

import numpy as np
import pandas as pd
import pandas_ta as ta

# ... (tutto il codice iniziale fino a get_macro_regime_from_context è identico, omesso per brevità) ...
warnings.filterwarnings("ignore", category=FutureWarning)
logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
try:
    import ccxt
except Exception: raise RuntimeError("ccxt è richiesto.")
TF_TO_SECONDS = {"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400,"1d":86400}
DEFAULT_CONTEXT_TF=["1d","4h"]; DEFAULT_SIGNAL_TF=["1h","30m","15m"]
def _now_utc_ms(): return int(pd.Timestamp.utcnow().timestamp() * 1000)
def _months_ago_ms(months:int): return int((pd.Timestamp.utcnow()-pd.DateOffset(months=months)).timestamp()*1000)
def fetch_ohlcv_all(exchange, symbol, timeframe, since_ms, limit=1000):
    out, step_ms, cursor = [], TF_TO_SECONDS.get(timeframe,3600)*1000, since_ms
    while True:
        try: batch = exchange.fetch_ohlcv(symbol, timeframe, since=cursor, limit=limit)
        except Exception as e: logging.warning(f"fetch_ohlcv_all error {symbol} {timeframe}: {e}"); break
        if not batch: break
        out.extend(batch); last_ts=batch[-1][0]; cursor=last_ts+step_ms
        if len(batch)<limit or cursor>=_now_utc_ms(): break
        time.sleep(getattr(exchange,"rateLimit",300)/1000.0)
    return out
def to_dataframe(ohlcv):
    if not ohlcv: return pd.DataFrame()
    df=pd.DataFrame(ohlcv,columns=["timestamp","open","high","low","close","volume"]);
    for c in ["open","high","low","close","volume"]: df[c]=pd.to_numeric(df[c],errors="coerce")
    df.dropna(inplace=True); df["timestamp"]=pd.to_datetime(df["timestamp"],unit="ms",utc=True)
    return df
def split_walk_forward(df,train_ratio=0.7): n=len(df); cut=int(n*train_ratio); return df.iloc[:cut].copy(), df.iloc[cut:].copy()
def risk_metrics(pnl_series):
    if not isinstance(pnl_series,list) or len(pnl_series)<2: return {"mdd":0.0,"sharpe":0.0,"calmar":0.0}
    equity=np.cumsum(pnl_series); dd=equity-np.maximum.accumulate(equity); mdd=float(abs(dd.min())); ret=np.diff(equity)
    if ret.size==0 or np.std(ret)==0: return {"mdd":mdd,"sharpe":0.0,"calmar":0.0}
    sharpe=float(np.mean(ret)/(np.std(ret)+1e-9)*np.sqrt(252)); ann_ret=float(np.mean(ret)*252)
    calmar=float(ann_ret/(mdd+1e-9)) if mdd>0 else 0.0
    return {"mdd":round(mdd,4),"sharpe":round(sharpe,3),"calmar":round(calmar,3)}
@dataclass
class Costs: fee_bps_per_side:float=5.0; slip_bps:float=2.0
def apply_costs(entry,exit_,side,costs:Costs):
    fee=costs.fee_bps_per_side/10000.0; slip=costs.slip_bps/10000.0
    if side=="LONG": entry_eff=entry*(1+slip); exit_eff=exit_*(1-slip); gross=exit_eff-entry_eff
    else: entry_eff=entry*(1-slip); exit_eff=exit_*(1+slip); gross=entry_eff-exit_eff
    fees=(entry_eff*fee)+(exit_eff*fee); return gross-fees
@dataclass
class BTConfig: costs:Costs; max_holding_bars:int=200; min_trades:int=20

# --- BUGFIX NELLA FUNZIONE get_macro_regime_from_context ---
def get_macro_regime_from_context(df_ctx):
    ema_length = 200
    # Guardia rinforzata: controlla se ci sono abbastanza dati per l'EMA
    if df_ctx.empty or len(df_ctx) < ema_length:
        return "RANGE"
    
    ema = ta.ema(df_ctx["close"], length=ema_length)
    
    # Guardia post-calcolo: controlla che l'EMA non sia None o piena di NaN
    if ema is None or ema.isna().all():
        return "RANGE"
        
    # Ora possiamo accedere a .iloc[-2] in sicurezza
    if df_ctx["close"].iloc[-2] > ema.iloc[-2]:
        return "UP"
    elif df_ctx["close"].iloc[-2] < ema.iloc[-2]:
        return "DOWN"
        
    return "RANGE"

# ... (tutto il resto del codice è identico, omesso per brevità) ...
def ensure_indicators(df,p):
    out=df.copy()
    if "EMA200" not in out.columns: out["EMA200"]=ta.ema(out["close"],length=200)
    atr_len=int(p.get("atr_len",14)); out["ATR"]=ta.atr(out["high"],out["low"],out["close"],length=atr_len)
    if any(k in p for k in ["shortPeriod","longPeriod"]):
        out["log_ret"]=np.log(out["close"]/out["close"].shift(1))
        sp,lp,ao,sg=int(p.get("shortPeriod",30)),int(p.get("longPeriod",200)),float(p.get("almaOffset",0.95)),float(p.get("almaSigma",4))
        out[f"ALMA_S_{sp}"]=ta.alma(out["log_ret"],length=sp,offset=ao,sigma=sg)
        out[f"ALMA_L_{lp}"]=ta.alma(out["log_ret"],length=lp,offset=ao,sigma=sg)
        out["EMA_MACRO"]=ta.ema(out["close"],length=int(p.get("macroEmaPeriod",200)))
    if "bb_len" in p:
        bb=ta.bbands(out["close"],length=int(p["bb_len"]),std=float(p.get("bb_std",2.0)))
        if bb is not None and not bb.empty:
            out["BBL"],out["BBM"],out["BBU"]=bb.iloc[:,0],bb.iloc[:,1],bb.iloc[:,2]
            out["BBW"]=(out["BBU"]-out["BBL"])/out["BBM"]
    return out.dropna()
def gen_signals_hermes(df,p,macro_regime):
    entries=[]; sp,lp=int(p.get("shortPeriod",30)),int(p.get("longPeriod",200)); rr=float(p.get("rr",1.5))
    min_strength=float(p.get("minCrossoverStrength",0.0001)); s_col=f"ALMA_S_{sp}"; l_col=f"ALMA_L_{lp}"
    if any(c not in df.columns for c in [s_col,l_col,"EMA_MACRO","ATR"]): return entries
    bullish=df[s_col]>df[l_col]; bearish=df[s_col]<df[l_col]; in_bull=df["close"]>df["EMA_MACRO"]; in_bear=df["close"]<df["EMA_MACRO"]
    for i in range(3,len(df)):
        strength=float(abs(df[s_col].iloc[i]-df[l_col].iloc[i]));
        if strength<min_strength: continue
        entry=float(df["close"].iloc[i]); atr=float(df["ATR"].iloc[i])
        if (macro_regime=="UP" and bullish.iloc[i] and in_bull.iloc[i]) or (macro_regime=="RANGE" and bullish.iloc[i]):
            sl=entry-atr; tp=entry+rr*atr; entries.append((i,"LONG",entry,sl,tp))
        elif (macro_regime=="DOWN" and bearish.iloc[i] and in_bear.iloc[i]) or (macro_regime=="RANGE" and bearish.iloc[i]):
            sl=entry+atr; tp=entry-rr*atr; entries.append((i,"SHORT",entry,sl,tp))
    return entries
def gen_signals_hermes_reversal(df,p,macro_regime):
    entries=[]; sp=int(p.get("shortPeriod",30)); lp=int(p.get("longPeriod",200)); rr=float(p.get("rr",1.2))
    s_col=f"ALMA_S_{sp}"; l_col=f"ALMA_L_{lp}"
    if any(c not in df.columns for c in [s_col,l_col,"ATR"]): return entries
    for i in range(3,len(df)):
        entry=float(df["close"].iloc[i]); atr=float(df["ATR"].iloc[i])
        if (df[s_col].iloc[i-1]<df[l_col].iloc[i-1]) and (df[s_col].iloc[i]>df[l_col].iloc[i]):
            sl=entry-atr; tp=entry+rr*atr; entries.append((i,"LONG",entry,sl,tp))
        elif (df[s_col].iloc[i-1]>df[l_col].iloc[i-1]) and (df[s_col].iloc[i]<df[l_col].iloc[i]):
            sl=entry+atr; tp=entry-rr*atr; entries.append((i,"SHORT",entry,sl,tp))
    return entries
def gen_signals_bb_break(df,p,macro_regime):
    entries=[]; rr=float(p.get("rr",1.5))
    if any(c not in df.columns for c in ["BBL","BBM","BBU","BBW","ATR"]): return entries
    for i in range(2,len(df)):
        c=df.iloc[i]
        if c["BBW"]<float(p.get("bbw_min",0.04)): continue
        entry=float(c["close"]); atr=float(c["ATR"])
        if (macro_regime in ["UP","RANGE"]) and c["close"]>c["BBU"]: sl=entry-atr; tp=entry+rr*atr; entries.append((i,"LONG",entry,sl,tp))
        elif (macro_regime in ["DOWN","RANGE"]) and c["close"]<c["BBL"]: sl=entry+atr; tp=entry-rr*atr; entries.append((i,"SHORT",entry,sl,tp))
    return entries
STRATEGY_GEN_MAP={"HERMES_ALMA_V2":gen_signals_hermes,"HERMES_REVERSAL":gen_signals_hermes_reversal,"BB_BREAK":gen_signals_bb_break}
def simulate_trades(df,entries,cfg):
    wins,losses,pnl_list,trades=0,0,[],0
    for i,side,entry,sl,tp in entries:
        if i>=len(df)-1: continue
        exit_, res = None, None
        last_idx=min(i+cfg.max_holding_bars,len(df)-1)
        for j in range(i+1,last_idx+1):
            hi,lo=df["high"].iloc[j],df["low"].iloc[j]
            if side=="LONG" and lo<=sl: exit_,res=sl,-1; break
            elif side=="LONG" and hi>=tp: exit_,res=tp,1; break
            elif side=="SHORT" and hi>=sl: exit_,res=sl,-1; break
            elif side=="SHORT" and lo<=tp: exit_,res=tp,1; break
        else: exit_=float(df["close"].iloc[last_idx]); raw=(exit_-entry) if side=="LONG" else (entry-exit_); res=1 if raw>0 else -1
        pnl=apply_costs(entry,exit_,side,cfg.costs); pnl_list.append(pnl); trades+=1; wins+=int(pnl>0)
    if trades==0: return dict(trades=0,wr=0.0,pf=0.0,score=0.0)
    pnl_arr=np.array(pnl_list); wr=wins/trades*100; gp=np.sum(pnl_arr[pnl_arr>0]) or 0; gl=abs(np.sum(pnl_arr[pnl_arr<0])) or 0
    pf=(gp/gl) if gl>1e-12 else float("inf"); exp=np.mean(pnl_arr)
    score=exp*(math.log1p(trades))*(min(pf,5.0))*(wr/50.0); rm=risk_metrics(pnl_list)
    return dict(trades=trades,wr=round(wr,2),pf=round(pf,2),score=round(score,3),**rm)
def backtest_single(df,strategy,params,cfg,macro_regime):
    df_i=ensure_indicators(df,params)
    if df_i.empty or len(df_i)<250: return {"ok":False}
    gen=STRATEGY_GEN_MAP[strategy]; entries=gen(df_i,params,macro_regime)
    metrics=simulate_trades(df_i,entries,cfg)
    metrics.update({"ok":True,"strategy":strategy,"params":params})
    return metrics
def mp_worker(args):
    df,strategy,params,cfg_dict,macro_regime=args
    cfg=BTConfig(costs=Costs(**cfg_dict["costs"]),max_holding_bars=cfg_dict["max_holding_bars"],min_trades=cfg_dict["min_trades"])
    try: return backtest_single(df,strategy,params,cfg,macro_regime)
    except Exception as e: logging.error(f"Worker {strategy} err {e}"); return {"ok":False,"strategy":strategy,"error":str(e)}
class LeoOptimizerV9Fix:
    def __init__(self,args):
        self.args=args; self.exchange=ccxt.bybit({"options":{"defaultType":"swap"}})
        self.processes=args.processes or max(1,cpu_count()-1)
        self.context_tf=args.context_tf.split(","); self.signal_tf=args.signal_tf.split(",")
        self.months=args.months; self.book_path=args.book; self.params_cache_path=args.params_cache
        self.bt_cfg=BTConfig(costs=Costs(fee_bps_per_side=args.fee_bps,slip_bps=args.slip_bps),max_holding_bars=args.max_hold,min_trades=args.mintrades)
        self.param_grids=self._make_param_grids(); self.adaptive_params=self._load_cache()
        logging.info(f"🦁 LeoOptimizer v9.4 (Robust) avviato con {self.processes} core")
    def _make_param_grids(self):
        grids={};
        grids["HERMES_ALMA_V2"]=[{"shortPeriod":sp,"longPeriod":lp,"almaOffset":ao,"almaSigma":sg,"rr":rr,"minCrossoverStrength":ms,"macroEmaPeriod":mep,"atr_len":14} for sp,lp,ao,sg,rr,ms,mep in product([15,20,25,30],[100,150,200],[0.9,0.95],[3.0,4.0],[1.3,1.5,1.8],[0.00005,0.0001,0.00015],[100,150,200]) if sp<lp]
        grids["HERMES_REVERSAL"]=grids["HERMES_ALMA_V2"]
        grids["BB_BREAK"]=[{"bb_len":20,"rr":1.5,"bbw_min":0.04,"atr_len":14}]
        return grids
    def _load_cache(self):
        try:
            with open(self.params_cache_path,"r") as f: return json.load(f)
        except: return {}
    def _save_cache(self):
        os.makedirs(os.path.dirname(self.params_cache_path),exist_ok=True)
        with open(self.params_cache_path,"w") as f: json.dump(self.adaptive_params,f,indent=4)
    def discover_assets(self,top):
        logging.info(f"🔭 Scopro top {top} mercati Bybit...")
        mk=self.exchange.fetch_markets(); tk=self.exchange.fetch_tickers()
        cands=[(m["symbol"],(tk.get(m["symbol"]) or {}).get("quoteVolume",0)) for m in mk if m.get("linear") and m.get("settle")=="USDT" and m.get("active")]
        cands=[c for c in cands if c[1] and c[1]>5_000_000]; cands.sort(key=lambda x:x[1],reverse=True)
        return [s for s,_ in cands[:top]]
    
    # --- BUGFIX NELLA FUNZIONE get_macro ---
    def get_macro(self, sym):
        for ctx_tf in self.context_tf:
            df = self.get_history(sym, ctx_tf)
            # Controllo rinforzato
            if not df.empty and len(df) > 200: 
                regime = get_macro_regime_from_context(df)
                # Controlla che il regime non sia None o vuoto
                if regime:
                    return regime, ctx_tf
        return "RANGE", "NA" # Fallback sicuro

    def get_history(self,sym,tf): return to_dataframe(fetch_ohlcv_all(self.exchange,sym,tf,_months_ago_ms(self.months)))
    def run(self):
        assets=self.args.assets.split(",") if self.args.mode=="manual" else self.discover_assets(self.args.top)
        book_data = {}
        if self.args.resume and os.path.exists(self.book_path):
            try:
                with open(self.book_path) as f: book_data=json.load(f)
                done=list(book_data.keys()); assets=[a for a in assets if a not in done]
            except json.JSONDecodeError:
                logging.warning("File book esistente corrotto. Riavvio da zero.")
                book_data = {}

        if not assets: logging.warning("Nessun nuovo asset da analizzare."); return
        for sym in assets:
            logging.info(f"=== ▶ Analisi {sym} ===")
            macro,ctx=self.get_macro(sym); logging.info(f"{sym} regime: {macro}")
            if ctx == "NA":
                logging.warning(f"Dati di contesto insufficienti per {sym}. Salto.")
                continue
            all_strats=[]
            for sig_tf in self.signal_tf:
                df=self.get_history(sym,sig_tf)
                if df.empty or len(df)<600: continue
                df_train,df_test=split_walk_forward(df)
                for sname,grid in self.param_grids.items():
                    cfg={"costs":asdict(self.bt_cfg.costs),"max_holding_bars":self.bt_cfg.max_holding_bars,"min_trades":self.bt_cfg.min_trades}
                    tasks=[(df_train,sname,p,cfg,macro) for p in grid]
                    with Pool(self.processes) as pool: res=pool.map(mp_worker,tasks)
                    res=[r for r in res if r and r.get("ok")];
                    if not res: continue
                    res.sort(key=lambda x:x.get("score",0),reverse=True); top=res[:3]
                    for tr in top:
                        test=backtest_single(df_test.copy(),sname,tr["params"],self.bt_cfg,macro)
                        if test.get("ok") and test.get("sharpe",0)>self.args.sharpe_min:
                            bonus=1.2 if sname.startswith("HERMES") and "BB_BREAK" in self.param_grids else 1.0
                            score_adj=test.get("score",0)*bonus
                            logging.warning(f"✅ {sym}|{sname}|{sig_tf} Sharpe={test.get('sharpe')} PF={test.get('pf')} Score={round(score_adj,3)}")
                            all_strats.append({"strategy_id":f"{sname}_{ctx}_{sig_tf}_{len(all_strats)}","strategy":sname,"context_tf":ctx,"signal_tf":sig_tf,"params":tr["params"],"quality_test":{k:v for k,v in test.items() if k not in ['ok','params','strategy']},"score_adj":round(score_adj,3)})
                            self.adaptive_params[f"{sym}|{sname}|{sig_tf}"]=tr["params"]
            if all_strats: book_data[sym]=all_strats
            else: logging.info(f"📉 Nessuna strategia trovata per {sym}.")
        if book_data:
            os.makedirs(os.path.dirname(self.book_path),exist_ok=True)
            with open(self.book_path,"w") as f: json.dump(book_data,f,indent=4)
            self._save_cache(); logging.info("✅ Analisi completata e salvata.")

if __name__=="__main__":
    parser=argparse.ArgumentParser(description="Leo Optimizer v9.4 — Robustness Update")
    parser.add_argument("--mode",type=str,default="discover",choices=["discover","manual"])
    parser.add_argument("--assets",type=str,default="BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT")
    parser.add_argument("--months",type=int,default=24); parser.add_argument("--top",type=int,default=40)
    parser.add_argument("--context_tf",type=str,default="1d,4h"); parser.add_argument("--signal_tf",type=str,default="1h,30m,15m")
    parser.add_argument("--processes",type=int,default=max(1,cpu_count()-1))
    parser.add_argument("--resume",action="store_true",help="Salta asset già testati nel JSON esistente")
    parser.add_argument("--mintrades",type=int,default=15); parser.add_argument("--sharpe_min",type=float,default=0.4)
    parser.add_argument("--max_hold",type=int,default=200)
    parser.add_argument("--fee_bps",type=float,default=5.0); parser.add_argument("--slip_bps",type=float,default=2.0)
    parser.add_argument("--book",type=str,default="config/strategy_book_fix.json")
    parser.add_argument("--params_cache",type=str,default="config/adaptive_params_fix.json")
    args=parser.parse_args()
    LeoOptimizerV9Fix(args).run()
