import React, { useState } from 'react';
import { View, Text, ScrollView, StyleSheet, TouchableOpacity, RefreshControl } from 'react-native';
import { useBot } from '../context/BotContext';
import { TradeItem } from '../components/TradeItem';
import { colors } from '../constants/colors';

type Tab = 'open' | 'closed';

export function TradesScreen() {
  const { openTrades, recentTrades, refresh, isRefreshing } = useBot();
  const [tab, setTab] = useState<Tab>('open');

  const closedTrades = recentTrades.filter(t => !t.is_open);
  const wins = closedTrades.filter(t => t.profit_pct > 0).length;
  const losses = closedTrades.filter(t => t.profit_pct <= 0).length;
  const totalPnl = closedTrades.reduce((sum, t) => sum + t.profit_abs, 0);

  return (
    <View style={styles.container}>
      {/* Tabs */}
      <View style={styles.tabs}>
        {(['open', 'closed'] as Tab[]).map(t => (
          <TouchableOpacity
            key={t}
            style={[styles.tab, tab === t && styles.tabActive]}
            onPress={() => setTab(t)}
          >
            <Text style={[styles.tabText, tab === t && styles.tabTextActive]}>
              {t === 'open' ? `Aperti (${openTrades.length})` : `Storico (${closedTrades.length})`}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Summary bar per closed */}
      {tab === 'closed' && closedTrades.length > 0 && (
        <View style={styles.summary}>
          <View style={styles.summaryItem}>
            <Text style={styles.summaryLabel}>Win</Text>
            <Text style={[styles.summaryValue, { color: colors.green }]}>{wins}</Text>
          </View>
          <View style={styles.summaryItem}>
            <Text style={styles.summaryLabel}>Loss</Text>
            <Text style={[styles.summaryValue, { color: colors.red }]}>{losses}</Text>
          </View>
          <View style={styles.summaryItem}>
            <Text style={styles.summaryLabel}>P&L</Text>
            <Text style={[styles.summaryValue, { color: totalPnl >= 0 ? colors.green : colors.red }]}>
              {totalPnl >= 0 ? '+' : ''}{totalPnl.toFixed(2)}
            </Text>
          </View>
          <View style={styles.summaryItem}>
            <Text style={styles.summaryLabel}>Winrate</Text>
            <Text style={styles.summaryValue}>
              {closedTrades.length ? ((wins / closedTrades.length) * 100).toFixed(0) : 0}%
            </Text>
          </View>
        </View>
      )}

      <ScrollView
        style={styles.list}
        refreshControl={<RefreshControl refreshing={isRefreshing} onRefresh={refresh} tintColor={colors.accent} />}
      >
        {tab === 'open' && (
          <>
            {openTrades.length === 0 ? (
              <View style={styles.empty}>
                <Text style={styles.emptyText}>Nessun trade aperto</Text>
              </View>
            ) : (
              openTrades.map(t => (
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
              ))
            )}
          </>
        )}

        {tab === 'closed' && (
          <>
            {closedTrades.length === 0 ? (
              <View style={styles.empty}>
                <Text style={styles.emptyText}>Nessun trade chiuso</Text>
              </View>
            ) : (
              closedTrades.map(t => (
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
              ))
            )}
          </>
        )}
        <View style={{ height: 30 }} />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  tabs: { flexDirection: 'row', padding: 12, gap: 8 },
  tab: { flex: 1, paddingVertical: 10, borderRadius: 10, backgroundColor: colors.bgCard, alignItems: 'center', borderWidth: 1, borderColor: colors.border },
  tabActive: { backgroundColor: colors.accentDim, borderColor: colors.accent },
  tabText: { color: colors.textSecondary, fontWeight: '600', fontSize: 13 },
  tabTextActive: { color: colors.accent },
  summary: { flexDirection: 'row', marginHorizontal: 12, backgroundColor: colors.bgCard, borderRadius: 12, padding: 12, marginBottom: 4, borderWidth: 1, borderColor: colors.border },
  summaryItem: { flex: 1, alignItems: 'center' },
  summaryLabel: { color: colors.textSecondary, fontSize: 11, marginBottom: 4 },
  summaryValue: { color: colors.text, fontSize: 16, fontWeight: '700' },
  list: { flex: 1, paddingHorizontal: 12 },
  empty: { alignItems: 'center', padding: 40 },
  emptyText: { color: colors.textSecondary, fontSize: 15 },
});
