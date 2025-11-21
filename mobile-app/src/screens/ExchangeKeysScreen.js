import React, { useState, useEffect } from 'react';
import { View, StyleSheet, ScrollView, Alert } from 'react-native';
import { Card, Title, Text, Button, TextInput, List } from 'react-native-paper';
import { exchangeAPI } from '../services/api';

export default function ExchangeKeysScreen() {
  const [keys, setKeys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAddForm, setShowAddForm] = useState(false);
  const [exchangeName, setExchangeName] = useState('bybit');
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    loadKeys();
  }, []);

  const loadKeys = async () => {
    try {
      const data = await exchangeAPI.getKeys();
      setKeys(data);
    } catch (error) {
      console.error('Failed to load keys:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleAddKey = async () => {
    if (!apiKey || !apiSecret) {
      Alert.alert('Error', 'Please fill in all fields');
      return;
    }

    setSubmitting(true);
    try {
      await exchangeAPI.addKey(exchangeName, apiKey, apiSecret);
      Alert.alert('Success', 'API key added successfully');
      setApiKey('');
      setApiSecret('');
      setShowAddForm(false);
      await loadKeys();
    } catch (error) {
      Alert.alert('Error', error.response?.data?.detail || 'Failed to add key');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteKey = (keyId) => {
    Alert.alert(
      'Delete API Key',
      'Are you sure you want to delete this API key?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            try {
              await exchangeAPI.deleteKey(keyId);
              Alert.alert('Success', 'API key deleted');
              await loadKeys();
            } catch (error) {
              Alert.alert('Error', 'Failed to delete key');
            }
          },
        },
      ]
    );
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
          <Title>Exchange API Keys</Title>
          <Text style={styles.subtitle}>
            Connect your exchange account to enable trading
          </Text>
        </Card.Content>
      </Card>

      {keys.length === 0 && !showAddForm && (
        <Card style={styles.card}>
          <Card.Content>
            <Text style={styles.emptyText}>
              No API keys configured yet. Add one to get started.
            </Text>
          </Card.Content>
        </Card>
      )}

      {keys.map((key) => (
        <Card key={key.id} style={styles.card}>
          <Card.Content>
            <List.Item
              title={key.exchange_name.toUpperCase()}
              description={`Added ${new Date(key.created_at).toLocaleDateString()}`}
              left={(props) => <List.Icon {...props} icon="key" />}
              right={(props) => (
                <Button
                  onPress={() => handleDeleteKey(key.id)}
                  textColor="red"
                >
                  Delete
                </Button>
              )}
            />
          </Card.Content>
        </Card>
      ))}

      {showAddForm ? (
        <Card style={styles.card}>
          <Card.Content>
            <Title>Add New API Key</Title>

            <TextInput
              label="Exchange"
              value={exchangeName}
              onChangeText={setExchangeName}
              style={styles.input}
              mode="outlined"
              placeholder="bybit, binance, etc."
            />

            <TextInput
              label="API Key"
              value={apiKey}
              onChangeText={setApiKey}
              style={styles.input}
              mode="outlined"
              autoCapitalize="none"
            />

            <TextInput
              label="API Secret"
              value={apiSecret}
              onChangeText={setApiSecret}
              style={styles.input}
              mode="outlined"
              secureTextEntry
              autoCapitalize="none"
            />

            <View style={styles.buttonRow}>
              <Button
                mode="outlined"
                onPress={() => {
                  setShowAddForm(false);
                  setApiKey('');
                  setApiSecret('');
                }}
                style={styles.halfButton}
              >
                Cancel
              </Button>
              <Button
                mode="contained"
                onPress={handleAddKey}
                loading={submitting}
                disabled={submitting}
                style={styles.halfButton}
              >
                Add Key
              </Button>
            </View>
          </Card.Content>
        </Card>
      ) : (
        <View style={styles.addButtonContainer}>
          <Button
            mode="contained"
            onPress={() => setShowAddForm(true)}
            icon="plus"
          >
            Add API Key
          </Button>
        </View>
      )}
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
  emptyText: {
    textAlign: 'center',
    color: '#999',
    marginVertical: 20,
  },
  input: {
    marginBottom: 15,
  },
  buttonRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 10,
  },
  halfButton: {
    flex: 1,
    marginHorizontal: 5,
  },
  addButtonContainer: {
    padding: 15,
  },
});
