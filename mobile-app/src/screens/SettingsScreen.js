import React, { useState, useEffect } from 'react';
import { View, StyleSheet, ScrollView, Alert } from 'react-native';
import { Card, Title, Text, Button, TextInput, Chip } from 'react-native-paper';
import { botAPI } from '../services/api';

const AVAILABLE_SYMBOLS = [
  'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT',
  'ADAUSDT', 'DOGEUSDT', 'AVAXUSDT', 'LINKUSDT', 'MATICUSDT'
];

export default function SettingsScreen({ navigation }) {
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [qtyUsdt, setQtyUsdt] = useState('');
  const [leverage, setLeverage] = useState('');
  const [selectedSymbols, setSelectedSymbols] = useState([]);

  useEffect(() => {
    loadConfig();
  }, []);

  const loadConfig = async () => {
    try {
      const data = await botAPI.getConfig();
      setConfig(data);
      setQtyUsdt(data.qty_usdt.toString());
      setLeverage(data.leverage.toString());
      setSelectedSymbols(data.symbols || []);
    } catch (error) {
      console.error('Failed to load config:', error);
    } finally {
      setLoading(false);
    }
  };

  const toggleSymbol = (symbol) => {
    if (selectedSymbols.includes(symbol)) {
      setSelectedSymbols(selectedSymbols.filter((s) => s !== symbol));
    } else {
      setSelectedSymbols([...selectedSymbols, symbol]);
    }
  };

  const handleSave = async () => {
    const qty = parseInt(qtyUsdt);
    const lev = parseInt(leverage);

    if (isNaN(qty) || qty < 10) {
      Alert.alert('Error', 'Position size must be at least $10');
      return;
    }

    if (isNaN(lev) || lev < 1 || lev > 20) {
      Alert.alert('Error', 'Leverage must be between 1 and 20');
      return;
    }

    if (selectedSymbols.length === 0) {
      Alert.alert('Error', 'Please select at least one trading pair');
      return;
    }

    setSaving(true);
    try {
      await botAPI.updateConfig({
        symbols: selectedSymbols,
        qty_usdt: qty,
        leverage: lev,
      });
      Alert.alert('Success', 'Settings saved successfully');
      navigation.goBack();
    } catch (error) {
      Alert.alert('Error', 'Failed to save settings');
    } finally {
      setSaving(false);
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
    <ScrollView style={styles.container}>
      <Card style={styles.card}>
        <Card.Content>
          <Title>Bot Configuration</Title>
          <Text style={styles.subtitle}>
            Configure your trading bot parameters
          </Text>
        </Card.Content>
      </Card>

      <Card style={styles.card}>
        <Card.Content>
          <Title style={styles.sectionTitle}>Trading Parameters</Title>

          <TextInput
            label="Position Size (USDT)"
            value={qtyUsdt}
            onChangeText={setQtyUsdt}
            keyboardType="numeric"
            style={styles.input}
            mode="outlined"
            placeholder="50"
          />

          <TextInput
            label="Leverage"
            value={leverage}
            onChangeText={setLeverage}
            keyboardType="numeric"
            style={styles.input}
            mode="outlined"
            placeholder="5"
          />
        </Card.Content>
      </Card>

      <Card style={styles.card}>
        <Card.Content>
          <Title style={styles.sectionTitle}>Trading Pairs</Title>
          <Text style={styles.subtitle}>
            Select the cryptocurrencies to trade
          </Text>

          <View style={styles.chipsContainer}>
            {AVAILABLE_SYMBOLS.map((symbol) => (
              <Chip
                key={symbol}
                selected={selectedSymbols.includes(symbol)}
                onPress={() => toggleSymbol(symbol)}
                style={styles.chip}
                mode={selectedSymbols.includes(symbol) ? 'flat' : 'outlined'}
              >
                {symbol.replace('USDT', '')}
              </Chip>
            ))}
          </View>
        </Card.Content>
      </Card>

      <View style={styles.buttonContainer}>
        <Button
          mode="contained"
          onPress={handleSave}
          loading={saving}
          disabled={saving}
          style={styles.saveButton}
        >
          Save Configuration
        </Button>
      </View>
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
    marginBottom: 10,
  },
  sectionTitle: {
    fontSize: 18,
    marginBottom: 10,
  },
  input: {
    marginBottom: 15,
  },
  chipsContainer: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    marginTop: 10,
  },
  chip: {
    margin: 5,
  },
  buttonContainer: {
    padding: 15,
  },
  saveButton: {
    paddingVertical: 5,
  },
});
