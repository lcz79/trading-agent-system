import * as SecureStore from 'expo-secure-store';

export interface BotConfig {
  baseUrl: string;
  username: string;
  password: string;
}

export interface OpenTrade {
  trade_id: number;
  pair: string;
  trade_direction: string;
  is_short: boolean;
  profit_pct: number;
  profit_abs: number;
  open_date: string;
  open_rate: number;
  current_rate: number;
  stake_amount: number;
  enter_tag: string;
  stop_loss_pct: number;
}

export interface ProfitStats {
  profit_closed_percent: number;
  profit_all_percent: number;
  trade_count: number;
  closed_trade_count: number;
  winning_trades: number;
  losing_trades: number;
  winrate: number;
  profit_factor: number;
  expectancy: number;
  avg_duration: string;
  best_pair: string;
  best_rate: number;
  max_drawdown: number;
  max_drawdown_abs: number;
  sharpe: number;
  sortino: number;
  latest_trade_date: string;
  bot_start_date: string;
}

export interface Balance {
  total: number;
  total_bot: number;
  starting_capital: number;
  starting_capital_pct: number;
  currencies: Array<{
    currency: string;
    free: number;
    balance: number;
    bot_owned: number;
  }>;
}

export interface Trade {
  trade_id: number;
  pair: string;
  trade_direction: string;
  is_short: boolean;
  is_open: boolean;
  profit_pct: number;
  profit_abs: number;
  open_date: string;
  close_date: string;
  exit_reason: string;
  stake_amount: number;
  open_rate: number;
  close_rate: number;
  enter_tag: string;
}

export interface PairPerformance {
  pair: string;
  profit_pct: number;
  profit_abs: number;
  count: number;
}

const CONFIG_KEY = 'bot_config';
let token: string | null = null;
let tokenExpiry: number = 0;

const defaultConfig: BotConfig = {
  baseUrl: 'http://207.154.212.99:8080',
  username: 'mitragliere',
  password: 'trading2026',
};

export async function getConfig(): Promise<BotConfig> {
  try {
    const stored = await SecureStore.getItemAsync(CONFIG_KEY);
    if (stored) return JSON.parse(stored);
  } catch {}
  return defaultConfig;
}

export async function saveConfig(config: BotConfig): Promise<void> {
  await SecureStore.setItemAsync(CONFIG_KEY, JSON.stringify(config));
  token = null;
  tokenExpiry = 0;
}

async function getToken(config?: BotConfig): Promise<string> {
  if (token && Date.now() < tokenExpiry) return token;
  const cfg = config || (await getConfig());
  const res = await fetch(`${cfg.baseUrl}/api/v1/token/login`, {
    method: 'POST',
    headers: { Authorization: 'Basic ' + btoa(`${cfg.username}:${cfg.password}`) },
  });
  if (!res.ok) throw new Error('Auth failed');
  const data = await res.json();
  token = data.access_token;
  tokenExpiry = Date.now() + 14 * 60 * 1000;
  return token!;
}

async function apiFetch(path: string): Promise<any> {
  const cfg = await getConfig();
  const tok = await getToken(cfg);
  const res = await fetch(`${cfg.baseUrl}${path}`, {
    headers: { Authorization: `Bearer ${tok}` },
  });
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

export async function testConnection(config: BotConfig): Promise<boolean> {
  try {
    const t = await getToken(config);
    return !!t;
  } catch {
    return false;
  }
}

export async function getOpenTrades(): Promise<OpenTrade[]> {
  return apiFetch('/api/v1/status');
}

export async function getProfitStats(): Promise<ProfitStats> {
  return apiFetch('/api/v1/profit');
}

export async function getBalance(): Promise<Balance> {
  return apiFetch('/api/v1/balance');
}

export async function getRecentTrades(limit = 20): Promise<{ trades: Trade[]; trades_count: number }> {
  return apiFetch(`/api/v1/trades?limit=${limit}`);
}

export async function getPerformance(): Promise<PairPerformance[]> {
  return apiFetch('/api/v1/performance');
}

export async function getBotConfig(): Promise<any> {
  return apiFetch('/api/v1/show_config');
}

export async function getLogs(limit = 50): Promise<{ logs: string[][] }> {
  return apiFetch(`/api/v1/logs?limit=${limit}`);
}

export async function sendBotCommand(command: 'start' | 'stop' | 'reload'): Promise<any> {
  const cfg = await getConfig();
  const tok = await getToken(cfg);
  const res = await fetch(`${cfg.baseUrl}/api/v1/${command}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' },
  });
  return res.json();
}
