import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors } from '../constants/colors';

interface Props {
  pair: string;
  direction: string;
  profitPct: number;
  profitAbs: number;
  openDate: string;
  closeDate?: string;
  exitReason?: string;
  enterTag?: string;
  isOpen?: boolean;
  currentRate?: number;
  openRate?: number;
}

export function TradeItem({
  pair, direction, profitPct, profitAbs, openDate, closeDate,
  exitReason, enterTag, isOpen, currentRate, openRate,
}: Props) {
  const isLong = !direction?.includes('short');
  const isProfit = profitPct >= 0;

  const formatDate = (d: string) => {
    if (!d) return '';
    const date = new Date(d);
    return date.toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit' }) +
      ' ' + date.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
  };

  return (
    <View style={styles.container}>
      <View style={styles.left}>
        <View style={[styles.dirBadge, { backgroundColor: isLong ? colors.greenDim : colors.redDim }]}>
          <Text style={[styles.dirText, { color: isLong ? colors.green : colors.red }]}>
            {isLong ? 'LONG' : 'SHORT'}
          </Text>
        </View>
        <Text style={styles.pair}>{pair.replace('/USDC:USDC', '').replace('/USDT:USDT', '')}</Text>
        {enterTag ? <Text style={styles.tag}>{enterTag}</Text> : null}
        <Text style={styles.date}>{formatDate(openDate)}</Text>
        {closeDate && !isOpen ? (
          <Text style={[styles.date, { color: colors.textDim }]}>→ {formatDate(closeDate)}</Text>
        ) : null}
      </View>

      <View style={styles.right}>
        <Text style={[styles.profit, { color: isProfit ? colors.green : colors.red }]}>
          {isProfit ? '+' : ''}{profitPct.toFixed(2)}%
        </Text>
        <Text style={[styles.profitAbs, { color: isProfit ? colors.green : colors.red }]}>
          {isProfit ? '+' : ''}{profitAbs.toFixed(2)} USDC
        </Text>
        {isOpen && currentRate && openRate ? (
          <Text style={styles.rate}>{currentRate.toFixed(4)}</Text>
        ) : null}
        {exitReason ? (
          <Text style={[styles.exit, exitReason === 'stop_loss' ? styles.stopLoss : exitReason === 'trailing_stop_loss' ? styles.trail : {}]}>
            {exitReason.replace('_', ' ')}
          </Text>
        ) : isOpen ? (
          <View style={styles.openDot} />
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: colors.bgCard,
    borderRadius: 12,
    padding: 14,
    marginVertical: 4,
    borderWidth: 1,
    borderColor: colors.border,
  },
  left: {
    flex: 1,
    gap: 3,
  },
  right: {
    alignItems: 'flex-end',
    gap: 3,
  },
  dirBadge: {
    alignSelf: 'flex-start',
    paddingHorizontal: 7,
    paddingVertical: 2,
    borderRadius: 5,
    marginBottom: 2,
  },
  dirText: {
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  pair: {
    color: colors.text,
    fontSize: 16,
    fontWeight: '700',
  },
  tag: {
    color: colors.accent,
    fontSize: 10,
  },
  date: {
    color: colors.textSecondary,
    fontSize: 11,
  },
  profit: {
    fontSize: 18,
    fontWeight: '700',
  },
  profitAbs: {
    fontSize: 12,
  },
  rate: {
    color: colors.textSecondary,
    fontSize: 11,
  },
  exit: {
    fontSize: 10,
    color: colors.textSecondary,
    backgroundColor: colors.bgCard2,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  stopLoss: {
    color: colors.red,
    backgroundColor: colors.redDim,
  },
  trail: {
    color: colors.green,
    backgroundColor: colors.greenDim,
  },
  openDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.green,
    marginTop: 4,
  },
});
