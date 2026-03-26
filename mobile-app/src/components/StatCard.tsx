import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { colors } from '../constants/colors';

interface Props {
  label: string;
  value: string;
  sub?: string;
  positive?: boolean | null;
  accent?: boolean;
  wide?: boolean;
}

export function StatCard({ label, value, sub, positive, accent, wide }: Props) {
  const valueColor = positive === null || positive === undefined
    ? colors.text
    : positive ? colors.green : colors.red;

  return (
    <View style={[styles.card, wide && styles.wide]}>
      <LinearGradient
        colors={accent ? [colors.accentDim, '#1a1830'] : [colors.bgCard, colors.bgCard2]}
        style={styles.gradient}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
      >
        <Text style={styles.label}>{label}</Text>
        <Text style={[styles.value, { color: valueColor }]}>{value}</Text>
        {sub ? <Text style={styles.sub}>{sub}</Text> : null}
      </LinearGradient>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flex: 1,
    margin: 4,
    borderRadius: 14,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: colors.border,
  },
  wide: {
    flex: 2,
  },
  gradient: {
    padding: 14,
    minHeight: 80,
    justifyContent: 'space-between',
  },
  label: {
    fontSize: 11,
    color: colors.textSecondary,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginBottom: 6,
  },
  value: {
    fontSize: 22,
    fontWeight: '700',
    color: colors.text,
  },
  sub: {
    fontSize: 11,
    color: colors.textSecondary,
    marginTop: 4,
  },
});
