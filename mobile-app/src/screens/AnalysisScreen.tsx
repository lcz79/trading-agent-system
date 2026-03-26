import React, { useState, useEffect } from 'react';
import {
  View, Text, ScrollView, StyleSheet, TouchableOpacity,
  ActivityIndicator, RefreshControl,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { useBot } from '../context/BotContext';
import { getRecentTrades, getLogs } from '../api/freqtradeApi';
import { colors } from '../constants/colors';

const PAIRS = ['BTC', 'ETH', 'SOL', 'DOGE', 'AVAX', 'ADA', 'SUI'];

export function AnalysisScreen() {
  const { recentTrades, openTrades, profitStats, refresh, isRefreshing } = useBot();
  const [logs, setLogs] = useState<string[][]>([]);
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [showLogs, setShowLogs] = useState(false);

  useEffect(() => {
    if (showLogs) loadLogs();
  }, [showLogs]);

  const loadLogs = async () => {
    setLoadingLogs(true);
    try {
      const data = await getLogs(30);
      setLogs(data.logs || []);
    } catch {}
    setLoadingLogs(false);
  };

  // Analisi per pair basata sui trade recenti
  const pairStats = PAIRS.map(symbol => {
    const pairName = `${symbol}/USDC:USDC`;
    const pairTrades = recentTrades.filter(t => t.pair === pairName);
    const openTrade = openTrades.find(t => t.pair === pairName);
    const closed = pairTrades.filter(t => !t.is_open);
    const wins = closed.filter(t => t.profit_pct > 0).length;
    const pnl = closed.reduce((s, t) => s + t.profit_pct, 0);
    const lastTrade = closed[0];

    return {
      symbol,
      pair: pairName,
      openTrade,
      totalTrades: closed.length,
      wins,
      losses: closed.length - wins,
      winrate: closed.length ? wins / closed.length : null,
      pnl,
      lastTrade,
      hasSignal: !!openTrade,
    };
  });

  // Decisioni recenti (exit reasons degli ultimi trade)
  const recentDecisions = recentTrades
    .filter(t => !t.is_open)
    .slice(0, 10)
    .map(t => ({
      pair: t.pair.replace('/USDC:USDC', ''),
      direction: t.is_short ? 'SHORT' : 'LONG',
      result: t.profit_pct >= 0 ? 'WIN' : 'LOSS',
      pct: t.profit_pct,
      reason: t.exit_reason,
      date: t.close_date,
      tag: t.enter_tag,
    }));

  const formatDate = (d: string) => {
    if (!d) return '';
    return new Date(d).toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
  };

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={isRefreshing} onRefresh={refresh} tintColor={colors.accent} />}
    >
      <Text style={styles.title}>Analisi & Decisioni</Text>

      {/* Stato attuale mercato per pair */}
      <Text style={styles.sectionTitle}>Stato per coppia</Text>
      <View style={styles.pairsGrid}>
        {pairStats.map((p) => {
          const hasOpen = !!p.openTrade;
          const isLong = hasOpen && !p.openTrade?.is_short;
          const pnlColor = p.pnl > 0 ? colors.green : p.pnl < 0 ? colors.red : colors.textSecondary;

          return (
            <LinearGradient
              key={p.symbol}
              colors={hasOpen
                ? (isLong ? [colors.greenDim, '#0d2d22'] : [colors.redDim, '#2d0d0d'])
                : [colors.bgCard, colors.bgCard2]}
              style={styles.pairCard}
              start={{ x: 0, y: 0 }}
              end={{ x: 1, y: 1 }}
            >
              <View style={styles.pairCardHeader}>
                <Text style={styles.pairSymbol}>{p.symbol}</Text>
                {hasOpen ? (
                  <View style={[styles.signalBadge, { backgroundColor: isLong ? colors.greenDim : colors.redDim }]}>
                    <Text style={[styles.signalText, { color: isLong ? colors.green : colors.red }]}>
                      {isLong ? '▲ LONG' : '▼ SHORT'}
                    </Text>
                  </View>
                ) : (
                  <Text style={styles.noSignal}>—</Text>
                )}
              </View>

              {hasOpen && p.openTrade && (
                <Text style={[styles.openProfit, { color: p.openTrade.profit_pct >= 0 ? colors.green : colors.red }]}>
                  {p.openTrade.profit_pct >= 0 ? '+' : ''}{p.openTrade.profit_pct.toFixed(2)}%
                </Text>
              )}

              <View style={styles.pairStats}>
                {p.totalTrades > 0 ? (
                  <>
                    <Text style={styles.pairStatText}>
                      {p.wins}W/{p.losses}L
                    </Text>
                    <Text style={[styles.pairStatText, { color: pnlColor }]}>
                      {p.pnl >= 0 ? '+' : ''}{p.pnl.toFixed(1)}%
                    </Text>
                  </>
                ) : (
                  <Text style={styles.pairStatText}>Nessun trade</Text>
                )}
              </View>
            </LinearGradient>
          );
        })}
      </View>

      {/* Ultime decisioni */}
      <Text style={[styles.sectionTitle, { marginTop: 16 }]}>Ultime decisioni</Text>
      {recentDecisions.length === 0 ? (
        <View style={styles.empty}>
          <Text style={styles.emptyText}>Nessuna decisione recente</Text>
        </View>
      ) : (
        recentDecisions.map((d, i) => {
          const isWin = d.result === 'WIN';
          const isTrail = d.reason === 'trailing_stop_loss';
          const isStop = d.reason === 'stop_loss';
          return (
            <View key={i} style={styles.decisionRow}>
              <View style={[styles.decisionIcon, {
                backgroundColor: isWin ? colors.greenDim : colors.redDim
              }]}>
                <Ionicons
                  name={isWin ? 'checkmark' : 'close'}
                  size={14}
                  color={isWin ? colors.green : colors.red}
                />
              </View>
              <View style={styles.decisionInfo}>
                <View style={styles.decisionTop}>
                  <Text style={styles.decisionPair}>{d.pair}</Text>
                  <Text style={[styles.decisionDir, { color: d.direction === 'LONG' ? colors.green : colors.red }]}>
                    {d.direction}
                  </Text>
                  {d.tag ? <Text style={styles.decisionTag}>{d.tag}</Text> : null}
                </View>
                <Text style={styles.decisionReason}>
                  Exit: <Text style={{
                    color: isTrail ? colors.green : isStop ? colors.red : colors.yellow
                  }}>{d.reason?.replace(/_/g, ' ')}</Text>
                  {'  '}{formatDate(d.date)}
                </Text>
              </View>
              <Text style={[styles.decisionPct, { color: isWin ? colors.green : colors.red }]}>
                {d.pct >= 0 ? '+' : ''}{d.pct.toFixed(2)}%
              </Text>
            </View>
          );
        })
      )}

      {/* Strategia info */}
      <View style={styles.strategyCard}>
        <Text style={styles.sectionTitle}>Strategia attiva</Text>
        <View style={styles.strategyRow}>
          <Ionicons name="git-branch-outline" size={14} color={colors.accent} />
          <Text style={styles.strategyName}>VolatilitySystemTrail</Text>
        </View>
        <Text style={styles.strategyDesc}>
          ATR Breakout su timeframe 3h con filtro macro SMA200.{'\n'}
          Trailing stop attivo dopo +15% di profitto (trail 5%).{'\n'}
          Leva 2x • Max 4 trade aperti • Orario: 06:00-02:00
        </Text>
        <View style={styles.strategyParams}>
          {[
            ['Timeframe', '1h (3h resample)'],
            ['Stop loss', '-15%'],
            ['Trail offset', '+15%'],
            ['Trail %', '5%'],
            ['Leva', '2x'],
            ['Max trade', '4'],
          ].map(([k, v]) => (
            <View key={k} style={styles.paramItem}>
              <Text style={styles.paramKey}>{k}</Text>
              <Text style={styles.paramValue}>{v}</Text>
            </View>
          ))}
        </View>
      </View>

      {/* Logs toggle */}
      <TouchableOpacity style={styles.logsToggle} onPress={() => setShowLogs(!showLogs)}>
        <Ionicons name={showLogs ? 'chevron-up' : 'chevron-down'} size={14} color={colors.accent} />
        <Text style={styles.logsToggleText}>{showLogs ? 'Nascondi log' : 'Mostra log recenti'}</Text>
      </TouchableOpacity>

      {showLogs && (
        <View style={styles.logsBox}>
          {loadingLogs ? (
            <ActivityIndicator color={colors.accent} />
          ) : (
            logs.slice(-20).reverse().map((log, i) => {
              const level = log[2] || '';
              const msg = log[3] || log.join(' ');
              const color = level === 'ERROR' ? colors.red
                : level === 'WARNING' ? colors.yellow
                : colors.textSecondary;
              return (
                <Text key={i} style={[styles.logLine, { color }]} numberOfLines={2}>
                  {log[1] ? log[1].split(' ')[1] : ''} {msg}
                </Text>
              );
            })
          )}
        </View>
      )}

      <View style={{ height: 30 }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  title: { color: colors.text, fontSize: 22, fontWeight: '800', marginBottom: 16 },
  sectionTitle: { color: colors.textSecondary, fontSize: 12, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 10 },
  pairsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 8 },
  pairCard: { width: '47%', borderRadius: 14, padding: 12, borderWidth: 1, borderColor: colors.border },
  pairCardHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 },
  pairSymbol: { color: colors.text, fontSize: 16, fontWeight: '800' },
  signalBadge: { paddingHorizontal: 7, paddingVertical: 3, borderRadius: 6 },
  signalText: { fontSize: 10, fontWeight: '700' },
  noSignal: { color: colors.textDim, fontSize: 14 },
  openProfit: { fontSize: 18, fontWeight: '700', marginBottom: 4 },
  pairStats: { flexDirection: 'row', justifyContent: 'space-between' },
  pairStatText: { color: colors.textSecondary, fontSize: 12 },
  empty: { alignItems: 'center', padding: 30 },
  emptyText: { color: colors.textSecondary },
  decisionRow: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.bgCard, borderRadius: 12, padding: 12, marginBottom: 6, gap: 10, borderWidth: 1, borderColor: colors.border },
  decisionIcon: { width: 28, height: 28, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  decisionInfo: { flex: 1 },
  decisionTop: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 3 },
  decisionPair: { color: colors.text, fontSize: 14, fontWeight: '700' },
  decisionDir: { fontSize: 11, fontWeight: '700' },
  decisionTag: { color: colors.accent, fontSize: 10, backgroundColor: colors.accentDim, paddingHorizontal: 5, paddingVertical: 1, borderRadius: 4 },
  decisionReason: { color: colors.textSecondary, fontSize: 11 },
  decisionPct: { fontSize: 16, fontWeight: '700' },
  strategyCard: { backgroundColor: colors.bgCard, borderRadius: 16, padding: 16, marginTop: 16, borderWidth: 1, borderColor: colors.border },
  strategyRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 10 },
  strategyName: { color: colors.accent, fontSize: 15, fontWeight: '700' },
  strategyDesc: { color: colors.textSecondary, fontSize: 12, lineHeight: 18, marginBottom: 14 },
  strategyParams: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  paramItem: { backgroundColor: colors.bgCard2, borderRadius: 8, padding: 8, minWidth: '30%' },
  paramKey: { color: colors.textDim, fontSize: 10, marginBottom: 2 },
  paramValue: { color: colors.text, fontSize: 13, fontWeight: '600' },
  logsToggle: { flexDirection: 'row', alignItems: 'center', gap: 6, padding: 12, marginTop: 8 },
  logsToggleText: { color: colors.accent, fontSize: 13, fontWeight: '600' },
  logsBox: { backgroundColor: colors.bgCard, borderRadius: 12, padding: 12, borderWidth: 1, borderColor: colors.border },
  logLine: { fontSize: 10, fontFamily: 'monospace', marginBottom: 3, lineHeight: 14 },
});
