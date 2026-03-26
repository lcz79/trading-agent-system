import React from 'react';
import { View, Text, ScrollView, StyleSheet, Dimensions, RefreshControl } from 'react-native';
import { LineChart, BarChart } from 'react-native-chart-kit';
import { useBot } from '../context/BotContext';
import { colors } from '../constants/colors';

const W = Dimensions.get('window').width;

const chartConfig = {
  backgroundColor: colors.bgCard,
  backgroundGradientFrom: colors.bgCard,
  backgroundGradientTo: colors.bgCard2,
  decimalPlaces: 0,
  color: (opacity = 1) => `rgba(108, 99, 255, ${opacity})`,
  labelColor: (opacity = 1) => `rgba(136, 136, 170, ${opacity})`,
  strokeWidth: 2,
  propsForDots: { r: '3', strokeWidth: '1', stroke: colors.accent },
};

export function PerformanceScreen() {
  const { recentTrades, performance, profitStats, balance, refresh, isRefreshing } = useBot();

  const closedTrades = recentTrades.filter(t => !t.is_open).slice().reverse();

  // Curva equity (cumulative PnL)
  const equityCurve = (() => {
    let cum = 0;
    const points = closedTrades.map(t => {
      cum += t.profit_pct;
      return parseFloat(cum.toFixed(2));
    });
    return points.length > 1 ? points : [0, 0];
  })();

  // Labels per curva (ogni 5 trade)
  const eqLabels = closedTrades.map((_, i) =>
    i % Math.max(1, Math.floor(closedTrades.length / 5)) === 0 ? String(i + 1) : ''
  );
  if (eqLabels.length < 2) eqLabels.push('', '');

  // Bar chart per pair performance
  const topPerf = performance.slice(0, 7);
  const perfLabels = topPerf.map(p => p.pair.replace('/USDC:USDC', '').replace('/USDT:USDT', ''));
  const perfData = topPerf.map(p => Math.abs(p.profit_pct));

  // Exit reasons breakdown
  const exitMap: Record<string, number> = {};
  closedTrades.forEach(t => {
    const r = t.exit_reason || 'unknown';
    exitMap[r] = (exitMap[r] || 0) + 1;
  });

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={isRefreshing} onRefresh={refresh} tintColor={colors.accent} />}
    >
      <Text style={styles.title}>Performance</Text>

      {/* Balance evolution */}
      {balance && (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Saldo account</Text>
          <View style={styles.balanceRow}>
            <View style={styles.balItem}>
              <Text style={styles.balLabel}>Attuale</Text>
              <Text style={styles.balValue}>{balance.total.toFixed(2)} USDC</Text>
            </View>
            <View style={styles.balItem}>
              <Text style={styles.balLabel}>Iniziale</Text>
              <Text style={styles.balValue}>{balance.starting_capital.toFixed(2)} USDC</Text>
            </View>
            <View style={styles.balItem}>
              <Text style={styles.balLabel}>P&L</Text>
              <Text style={[styles.balValue, { color: balance.starting_capital_pct >= 0 ? colors.green : colors.red }]}>
                {balance.starting_capital_pct >= 0 ? '+' : ''}{balance.starting_capital_pct.toFixed(2)}%
              </Text>
            </View>
          </View>
        </View>
      )}

      {/* Equity curve */}
      {closedTrades.length > 1 && (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Curva equity (P&L cumulativo %)</Text>
          <LineChart
            data={{ labels: eqLabels.slice(0, equityCurve.length), datasets: [{ data: equityCurve }] }}
            width={W - 48}
            height={180}
            chartConfig={{
              ...chartConfig,
              color: (opacity = 1) => {
                const last = equityCurve[equityCurve.length - 1];
                return last >= 0
                  ? `rgba(0, 212, 170, ${opacity})`
                  : `rgba(255, 71, 87, ${opacity})`;
              },
            }}
            bezier
            style={styles.chart}
            withDots={closedTrades.length < 30}
            withInnerLines={false}
          />
        </View>
      )}

      {/* Key metrics */}
      {profitStats && (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Metriche chiave</Text>
          <View style={styles.metricsGrid}>
            {[
              { label: 'Profit factor', value: profitStats.profit_factor.toFixed(2), good: profitStats.profit_factor > 1 },
              { label: 'Expectancy', value: profitStats.expectancy.toFixed(3), good: profitStats.expectancy > 0 },
              { label: 'Sharpe', value: profitStats.sharpe.toFixed(2), good: profitStats.sharpe > 1 },
              { label: 'Sortino', value: profitStats.sortino.toFixed(2), good: profitStats.sortino > 1 },
              { label: 'Max Drawdown', value: `${(profitStats.max_drawdown * 100).toFixed(2)}%`, good: false },
              { label: 'Win/Loss', value: `${profitStats.winning_trades}/${profitStats.losing_trades}`, good: profitStats.winning_trades > profitStats.losing_trades },
              { label: 'Winrate', value: `${(profitStats.winrate * 100).toFixed(1)}%`, good: profitStats.winrate > 0.5 },
              { label: 'Avg durata', value: profitStats.avg_duration.split(',')[0], good: null },
            ].map((m, i) => (
              <View key={i} style={styles.metricItem}>
                <Text style={styles.metricLabel}>{m.label}</Text>
                <Text style={[styles.metricValue, {
                  color: m.good === null ? colors.text : m.good ? colors.green : colors.red
                }]}>{m.value}</Text>
              </View>
            ))}
          </View>
        </View>
      )}

      {/* Per-pair performance */}
      {topPerf.length > 0 && (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Performance per coppia</Text>
          {topPerf.map((p, i) => (
            <View key={i} style={styles.pairRow}>
              <Text style={styles.pairName}>
                {p.pair.replace('/USDC:USDC', '').replace('/USDT:USDT', '')}
              </Text>
              <View style={styles.pairBarContainer}>
                <View style={[
                  styles.pairBar,
                  {
                    width: (Math.min(100, Math.abs(p.profit_pct) * 5) + '%') as any,
                    backgroundColor: p.profit_pct >= 0 ? colors.green : colors.red,
                  }
                ]} />
              </View>
              <Text style={[styles.pairPct, { color: p.profit_pct >= 0 ? colors.green : colors.red }]}>
                {p.profit_pct >= 0 ? '+' : ''}{p.profit_pct.toFixed(2)}%
              </Text>
              <Text style={styles.pairCount}>{p.count}x</Text>
            </View>
          ))}
        </View>
      )}

      {/* Exit reasons */}
      {Object.keys(exitMap).length > 0 && (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Motivi di uscita</Text>
          {Object.entries(exitMap).sort((a, b) => b[1] - a[1]).map(([reason, count], i) => {
            const color = reason === 'trailing_stop_loss' ? colors.green
              : reason === 'stop_loss' ? colors.red
              : reason === 'exit_signal' ? colors.yellow
              : colors.textSecondary;
            const total = closedTrades.length;
            const pct = total ? ((count / total) * 100).toFixed(0) : 0;
            return (
              <View key={i} style={styles.exitRow}>
                <View style={[styles.exitDot, { backgroundColor: color }]} />
                <Text style={styles.exitReason}>{reason.replace(/_/g, ' ')}</Text>
                <View style={styles.exitBarContainer}>
                  <View style={[styles.exitBar, { width: (pct + '%') as any, backgroundColor: color + '44' }]} />
                </View>
                <Text style={[styles.exitCount, { color }]}>{count} ({pct}%)</Text>
              </View>
            );
          })}
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
  card: { backgroundColor: colors.bgCard, borderRadius: 16, padding: 16, marginBottom: 12, borderWidth: 1, borderColor: colors.border },
  cardTitle: { color: colors.textSecondary, fontSize: 12, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 14 },
  balanceRow: { flexDirection: 'row', justifyContent: 'space-between' },
  balItem: { alignItems: 'center' },
  balLabel: { color: colors.textSecondary, fontSize: 11, marginBottom: 4 },
  balValue: { color: colors.text, fontSize: 15, fontWeight: '700' },
  chart: { borderRadius: 10, marginTop: 4 },
  metricsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  metricItem: { width: '47%', backgroundColor: colors.bgCard2, borderRadius: 10, padding: 12 },
  metricLabel: { color: colors.textSecondary, fontSize: 11, marginBottom: 4 },
  metricValue: { color: colors.text, fontSize: 17, fontWeight: '700' },
  pairRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 10, gap: 8 },
  pairName: { color: colors.text, fontSize: 13, fontWeight: '600', width: 52 },
  pairBarContainer: { flex: 1, height: 8, backgroundColor: colors.bgCard2, borderRadius: 4, overflow: 'hidden' },
  pairBar: { height: '100%', borderRadius: 4 },
  pairPct: { fontSize: 13, fontWeight: '700', width: 58, textAlign: 'right' },
  pairCount: { color: colors.textDim, fontSize: 11, width: 22 },
  exitRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 10, gap: 8 },
  exitDot: { width: 8, height: 8, borderRadius: 4 },
  exitReason: { color: colors.text, fontSize: 12, flex: 1 },
  exitBarContainer: { flex: 1, height: 6, backgroundColor: colors.bgCard2, borderRadius: 3, overflow: 'hidden' },
  exitBar: { height: '100%', borderRadius: 3 },
  exitCount: { fontSize: 12, fontWeight: '600', width: 72, textAlign: 'right' },
});
