import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import {
  getOpenTrades, getProfitStats, getBalance, getRecentTrades,
  getPerformance, getBotConfig,
  OpenTrade, ProfitStats, Balance, Trade, PairPerformance,
} from '../api/freqtradeApi';

interface BotState {
  status: 'loading' | 'online' | 'offline' | 'error';
  botRunning: boolean;
  strategy: string;
  dryRun: boolean;
  openTrades: OpenTrade[];
  profitStats: ProfitStats | null;
  balance: Balance | null;
  recentTrades: Trade[];
  performance: PairPerformance[];
  lastUpdate: Date | null;
  error: string | null;
  refresh: () => Promise<void>;
  isRefreshing: boolean;
}

const BotContext = createContext<BotState | null>(null);

export function BotProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<BotState['status']>('loading');
  const [botRunning, setBotRunning] = useState(false);
  const [strategy, setStrategy] = useState('');
  const [dryRun, setDryRun] = useState(false);
  const [openTrades, setOpenTrades] = useState<OpenTrade[]>([]);
  const [profitStats, setProfitStats] = useState<ProfitStats | null>(null);
  const [balance, setBalance] = useState<Balance | null>(null);
  const [recentTrades, setRecentTrades] = useState<Trade[]>([]);
  const [performance, setPerformance] = useState<PairPerformance[]>([]);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    setIsRefreshing(true);
    setError(null);
    try {
      const [trades, profit, bal, recent, perf, cfg] = await Promise.all([
        getOpenTrades(),
        getProfitStats(),
        getBalance(),
        getRecentTrades(30),
        getPerformance(),
        getBotConfig(),
      ]);
      setOpenTrades(trades);
      setProfitStats(profit);
      setBalance(bal);
      setRecentTrades(recent.trades || []);
      setPerformance(perf);
      setStrategy(cfg.strategy || '');
      setDryRun(cfg.dry_run || false);
      setBotRunning(cfg.state === 'running');
      setStatus('online');
      setLastUpdate(new Date());
    } catch (e: any) {
      setError(e.message || 'Connection failed');
      setStatus('error');
    } finally {
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    intervalRef.current = setInterval(refresh, 30000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [refresh]);

  return (
    <BotContext.Provider value={{
      status, botRunning, strategy, dryRun,
      openTrades, profitStats, balance, recentTrades, performance,
      lastUpdate, error, refresh, isRefreshing,
    }}>
      {children}
    </BotContext.Provider>
  );
}

export function useBot() {
  const ctx = useContext(BotContext);
  if (!ctx) throw new Error('useBot must be used within BotProvider');
  return ctx;
}
