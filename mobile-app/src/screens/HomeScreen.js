import React, { useState, useEffect } from 'react';
import { View, StyleSheet, ScrollView, RefreshControl } from 'react-native';
import { Card, Title, Text, Button, Switch, Chip } from 'react-native-paper';
import { useAuth } from '../contexts/AuthContext';
import { botAPI } from '../services/api';

export default function HomeScreen({ navigation }) {
  const { user } = useAuth();
  const [botConfig, setBotConfig] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadBotConfig();
  }, []);

  const loadBotConfig = async () => {
    try {
      const config = await botAPI.getConfig();
      setBotConfig(config);
    } catch (error) {
      console.error('Failed to load bot config:', error);
    } finally {
      setLoading(false);
    }
  };

  const onRefresh = async () => {
    setRefreshing(true);
    await loadBotConfig();
    setRefreshing(false);
  };

  const toggleBot = async () => {
    try {
      const newConfig = await botAPI.updateConfig({
        is_running: !botConfig.is_running,
      });
      setBotConfig(newConfig);
    } catch (error) {
      console.error('Failed to toggle bot:', error);
    }
  };

  if (loading) {
    return (
      <View style={styles.container}>
        <Text>Loading...</Text>
      </View>
    );
  }

  return (
    <ScrollView
      style={styles.container}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
      }
    >
      <Card style={styles.card}>
        <Card.Content>
          <Title>Welcome, {user?.username}! 👋</Title>
          <Text style={styles.subtitle}>Trading Bot Dashboard</Text>
        </Card.Content>
      </Card>

      <Card style={styles.card}>
        <Card.Content>
          <View style={styles.statusRow}>
            <Title style={styles.statusTitle}>Bot Status</Title>
            <View style={styles.statusBadge}>
              <Chip
                mode="flat"
                style={botConfig?.is_running ? styles.runningChip : styles.stoppedChip}
              >
                {botConfig?.is_running ? '🟢 Running' : '🔴 Stopped'}
              </Chip>
            </View>
          </View>

          <View style={styles.switchRow}>
            <Text>Enable Trading Bot</Text>
            <Switch value={botConfig?.is_running} onValueChange={toggleBot} />
          </View>
        </Card.Content>
      </Card>

      <Card style={styles.card}>
        <Card.Content>
          <Title>Bot Configuration</Title>
          <View style={styles.configItem}>
            <Text style={styles.configLabel}>Trading Pairs:</Text>
            <Text>{botConfig?.symbols?.join(', ') || 'None'}</Text>
          </View>
          <View style={styles.configItem}>
            <Text style={styles.configLabel}>Position Size:</Text>
            <Text>${botConfig?.qty_usdt} USDT</Text>
          </View>
          <View style={styles.configItem}>
            <Text style={styles.configLabel}>Leverage:</Text>
            <Text>{botConfig?.leverage}x</Text>
          </View>
          <Button
            mode="outlined"
            onPress={() => navigation.navigate('Settings')}
            style={styles.configButton}
          >
            Configure Bot
          </Button>
        </Card.Content>
      </Card>

      <Card style={styles.card}>
        <Card.Content>
          <Title>Exchange Connection</Title>
          <Text style={styles.subtitle}>
            Manage your exchange API keys
          </Text>
          <Button
            mode="contained"
            onPress={() => navigation.navigate('ExchangeKeys')}
            style={styles.button}
          >
            Manage API Keys
          </Button>
        </Card.Content>
      </Card>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f5f5f5',
  },
  card: {
    margin: 15,
    elevation: 2,
  },
  subtitle: {
    color: '#666',
    marginTop: 5,
  },
  statusRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 15,
  },
  statusTitle: {
    fontSize: 18,
  },
  statusBadge: {
    flexDirection: 'row',
  },
  runningChip: {
    backgroundColor: '#c8e6c9',
  },
  stoppedChip: {
    backgroundColor: '#ffcdd2',
  },
  switchRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 10,
  },
  configItem: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: '#e0e0e0',
  },
  configLabel: {
    fontWeight: 'bold',
  },
  configButton: {
    marginTop: 15,
  },
  button: {
    marginTop: 10,
  },
});
