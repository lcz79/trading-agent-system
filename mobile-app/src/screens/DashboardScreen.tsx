import React from 'react';
import {
  View, Text, ScrollView, StyleSheet, RefreshControl,
  TouchableOpacity, ActivityIndicator,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { useBot } from '../context/BotContext';
import { StatCard } from '../components/StatCard';
import { TradeItem } from '../components/TradeItem';
import { colors } from '../constants/colors';

export function DashboardScreen() {
  const { status, botRunning, strategy, dryRun, openTrades, profitStats, balance, recentTrades, lastUpdate, refresh, isRefreshing, error } = useBot();

  const totalPnl = balance ? balance.starting_capital_pct : 0;
  const isUp = totalPnl >= 0;
  const closedTrades = recentTrades.filter(t => !t.is_open);
  const lastTrades = closedTrades.slice(0, 3);

  const formatTime = (d: Date | null) => {
    if (!d) return '';
    return d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  if (status === 'loading') {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color={colors.accent} />
        <Text style={styles.loadingText}>Connessione al bot...</Text>
      </View>
    );
  }

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={isRefreshing} onRefresh={refresh} tintColor={colors.accent} />}
    >
      {/* Header */}
      <View style={styles.header}>
        <View>
          <Text style={styles.headerTitle}>Trading Bot</Text>
          <Text style={styles.headerSub}>
            {lastUpdate ? `Aggiornato: ${formatTime(lastUpdate)}` : 'Caricamento...'}
          </Text>
        </View>
        <View style={styles.headerRight}>
          {dryRun && <View style={styles.dryRunBadge}><Text style={styles.dryRunText}>DRY RUN</Text></View>}
          <View style={[styles.statusBadge, { backgroundColor: botRunning ? colors.greenDim : colors.redDim }]}>
            <View style={[styles.statusDot, { backgroundColor: botRunning ? colors.green : colors.red }]} />
            <Text style={[styles.statusText, { color: botRunning ? colors.green : colors.red }]}>
              {botRunning ? 'RUNNING' : 'STOPPED'}
            </Text>
          </View>
        </View>
      </View>

      {error && (
        <View style={styles.errorBanner}>
          <Ionicons name="warning-outline" size={16} color={colors.yellow} />
          <Text style={styles.errorText}>{error}</Text>
        </View>
      )}

      {/* Balance principale */}
      <LinearGradient
        colors={isUp ? [colors.greenDim, '#0d2d22'] : [colors.redDim, '#2d0d0d']}
        style={styles.balanceCard}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
      >
        <Text style={styles.balanceLabel}>SALDO TOTALE</Text>
        <Text style={styles.balanceValue}>
          {balance ? balance.total.toFixed(2) : '—'} USDC
        </Text>
        <View style={styles.balanceRow}>
          <Text style={[styles.balancePnl, { color: isUp ? colors.green : colors.red }]}>
            {isUp ? '+' : ''}{totalPnl.toFixed(2)}% da inizio
          </Text>
          <Text style={styles.balanceSub}>
            Capitale iniziale: {balance ? balance.starting_capital.toFixed(2) : '—'} USDC
          </Text>
        </View>
        <Text style={styles.strategyLabel}>{strategy}</Text>
      </LinearGradient>

      {/* Stats row 1 */}
      <View style={styles.row}>
        <StatCard
          label="Trade aperti"
          value={String(openTrades.length)}
          sub={`max 4`}
          positive={null}
        />
        <StatCard
          label="Trade chiusi"
          value={String(profitStats?.closed_trade_count ?? '—')}
          positive={null}
        />
        <StatCard
          label="Winrate"
          value={profitStats ? `${(profitStats.winrate * 100).toFixed(1)}%` : '—'}
          sub={profitStats ? `${profitStats.winning_trades}W / ${profitStats.losing_trades}L` : ''}
          positive={profitStats ? profitStats.winrate > 0.5 : null}
        />
      </View>

      {/* Stats row 2 */}
      <View style={styles.row}>
        <StatCard
          label="P&L chiusi"
          value={profitStats ? `${profitStats.profit_closed_percent >= 0 ? '+' : ''}${profitStats.profit_closed_percent.toFixed(2)}%` : '—'}
          positive={profitStats ? profitStats.profit_closed_percent >= 0 : null}
        />
        <StatCard
          label="Profit factor"
          value={profitStats ? profitStats.profit_factor.toFixed(2) : '—'}
          positive={profitStats ? profitStats.profit_factor > 1 : null}
        />
        <StatCard
          label="Max DD"
          value={profitStats ? `${(profitStats.max_drawdown * 100).toFixed(1)}%` : '—'}
          positive={false}
        />
      </View>

      {/* Stats row 3 */}
      <View style={styles.row}>
        <StatCard
          label="Sharpe"
          value={profitStats ? profitStats.sharpe.toFixed(2) : '—'}
          positive={profitStats ? profitStats.sharpe > 1 : null}
        />
        <StatCard
          label="Sortino"
          value={profitStats ? profitStats.sortino.toFixed(2) : '—'}
          positive={profitStats ? profitStats.sortino > 1 : null}
        />
        <StatCard
          label="Avg durata"
          value={profitStats ? profitStats.avg_duration.split(',')[0] : '—'}
          positive={null}
        />
      </View>

      {/* Trades aperti */}
      {openTrades.length > 0 && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>
            <Ionicons name="pulse-outline" size={14} color={colors.green} /> Trade aperti
          </Text>
          {openTrades.map(t => (
            <TradeItem
              key={t.trade_id}
              pair={t.pair}
              direction={t.trade_direction}
              profitPct={t.profit_pct}
              profitAbs={t.profit_abs}
              openDate={t.open_date}
              enterTag={t.enter_tag}
              isOpen
              currentRate={t.current_rate}
              openRate={t.open_rate}
            />
          ))}
        </View>
      )}

      {openTrades.length === 0 && (
        <View style={styles.noTradesBox}>
          <Ionicons name="search-outline" size={28} color={colors.textDim} />
          <Text style={styles.noTradesText}>Nessun trade aperto</Text>
          <Text style={styles.noTradesSub}>Il bot sta scansionando il mercato...</Text>
        </View>
      )}

      {/* Ultimi trade chiusi */}
      {lastTrades.length > 0 && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Ultimi trade chiusi</Text>
          {lastTrades.map(t => (
            <TradeItem
              key={t.trade_id}
              pair={t.pair}
              direction={t.trade_direction || (t.is_short ? 'short' : 'long')}
              profitPct={t.profit_pct}
              profitAbs={t.profit_abs}
              openDate={t.open_date}
              closeDate={t.close_date}
              exitReason={t.exit_reason}
              enterTag={t.enter_tag}
            />
          ))}
        </View>
      )}

      {/* Best pair */}
      {profitStats?.best_pair && (
        <View style={styles.bestPairCard}>
          <Ionicons name="trophy-outline" size={16} color={colors.yellow} />
          <Text style={styles.bestPairText}>
            Best pair: <Text style={{ color: colors.yellow }}>{profitStats.best_pair}</Text>
            {'  '}+{profitStats.best_rate.toFixed(2)}%
          </Text>
        </View>
      )}

      <View style={{ height: 20 }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: colors.bg, gap: 12 },
  loadingText: { color: colors.textSecondary, fontSize: 14 },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 },
  headerTitle: { color: colors.text, fontSize: 22, fontWeight: '800' },
  headerSub: { color: colors.textSecondary, fontSize: 11, marginTop: 2 },
  headerRight: { alignItems: 'flex-end', gap: 6 },
  statusBadge: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 10, paddingVertical: 5, borderRadius: 20, gap: 5 },
  statusDot: { width: 7, height: 7, borderRadius: 4 },
  statusText: { fontSize: 11, fontWeight: '700', letterSpacing: 0.5 },
  dryRunBadge: { backgroundColor: colors.yellowDim, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },
  dryRunText: { color: colors.yellow, fontSize: 10, fontWeight: '700' },
  errorBanner: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.yellowDim, borderRadius: 10, padding: 10, marginBottom: 12, gap: 8 },
  errorText: { color: colors.yellow, fontSize: 12, flex: 1 },
  balanceCard: { borderRadius: 18, padding: 20, marginBottom: 12, borderWidth: 1, borderColor: colors.border },
  balanceLabel: { color: colors.textSecondary, fontSize: 11, letterSpacing: 1, textTransform: 'uppercase' },
  balanceValue: { color: colors.text, fontSize: 36, fontWeight: '800', marginVertical: 6 },
  balanceRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 4 },
  balancePnl: { fontSize: 16, fontWeight: '700' },
  balanceSub: { color: colors.textSecondary, fontSize: 12 },
  strategyLabel: { color: colors.accent, fontSize: 12, marginTop: 8, fontWeight: '600' },
  row: { flexDirection: 'row', marginBottom: 4 },
  section: { marginTop: 16 },
  sectionTitle: { color: colors.textSecondary, fontSize: 13, fontWeight: '600', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 },
  noTradesBox: { alignItems: 'center', padding: 30, gap: 8, backgroundColor: colors.bgCard, borderRadius: 14, borderWidth: 1, borderColor: colors.border, marginTop: 12 },
  noTradesText: { color: colors.textSecondary, fontSize: 15, fontWeight: '600' },
  noTradesSub: { color: colors.textDim, fontSize: 12 },
  bestPairCard: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.bgCard, borderRadius: 12, padding: 12, gap: 8, marginTop: 8, borderWidth: 1, borderColor: colors.border },
  bestPairText: { color: colors.textSecondary, fontSize: 13 },
});
