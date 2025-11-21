import React from 'react';
import { View, StyleSheet } from 'react-native';
import { Card, Title, Text, Button, List } from 'react-native-paper';
import { useAuth } from '../contexts/AuthContext';

export default function ProfileScreen({ navigation }) {
  const { user, logout } = useAuth();

  const handleLogout = () => {
    logout();
  };

  return (
    <View style={styles.container}>
      <Card style={styles.card}>
        <Card.Content>
          <Title style={styles.title}>Profile</Title>
          <View style={styles.infoContainer}>
            <List.Item
              title="Username"
              description={user?.username}
              left={(props) => <List.Icon {...props} icon="account" />}
            />
            <List.Item
              title="Email"
              description={user?.email}
              left={(props) => <List.Icon {...props} icon="email" />}
            />
            <List.Item
              title="Member Since"
              description={new Date(user?.created_at).toLocaleDateString()}
              left={(props) => <List.Icon {...props} icon="calendar" />}
            />
          </View>
        </Card.Content>
      </Card>

      <Card style={styles.card}>
        <Card.Content>
          <Title style={styles.sectionTitle}>Account Actions</Title>
          <Button
            mode="contained"
            onPress={handleLogout}
            style={styles.logoutButton}
            buttonColor="#d32f2f"
          >
            Logout
          </Button>
        </Card.Content>
      </Card>

      <Card style={styles.card}>
        <Card.Content>
          <Title style={styles.sectionTitle}>About</Title>
          <Text style={styles.aboutText}>
            Trading Bot App v1.0.0
          </Text>
          <Text style={styles.aboutText}>
            Powered by AI agents for cryptocurrency trading
          </Text>
        </Card.Content>
      </Card>
    </View>
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
  title: {
    fontSize: 24,
    marginBottom: 20,
  },
  sectionTitle: {
    fontSize: 18,
    marginBottom: 10,
  },
  infoContainer: {
    marginTop: 10,
  },
  logoutButton: {
    marginTop: 10,
  },
  aboutText: {
    color: '#666',
    marginTop: 5,
  },
});
