import React from 'react';
import { StatusBar } from 'expo-status-bar';
import { NavigationContainer, DefaultTheme } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { Ionicons } from '@expo/vector-icons';

import { BotProvider, useBot } from './src/context/BotContext';
import { DashboardScreen } from './src/screens/DashboardScreen';
import { TradesScreen } from './src/screens/TradesScreen';
import { PerformanceScreen } from './src/screens/PerformanceScreen';
import { AnalysisScreen } from './src/screens/AnalysisScreen';
import { SettingsScreen } from './src/screens/SettingsScreen';
import { colors } from './src/constants/colors';
import { View, Text } from 'react-native';

const Tab = createBottomTabNavigator();

const navTheme = {
  ...DefaultTheme,
  colors: {
    ...DefaultTheme.colors,
    background: colors.bg,
    card: colors.bgCard,
    text: colors.text,
    border: colors.border,
    primary: colors.accent,
  },
};

function TabBadge({ count }: { count: number }) {
  if (!count) return null;
  return (
    <View style={{
      position: 'absolute', top: -4, right: -8,
      backgroundColor: colors.green, borderRadius: 8,
      minWidth: 16, height: 16, alignItems: 'center', justifyContent: 'center',
    }}>
      <Text style={{ color: '#000', fontSize: 10, fontWeight: '800' }}>{count}</Text>
    </View>
  );
}

function AppTabs() {
  const { openTrades } = useBot();

  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerStyle: { backgroundColor: colors.bgCard, borderBottomColor: colors.border, borderBottomWidth: 1 },
        headerTitleStyle: { color: colors.text, fontWeight: '700' },
        tabBarStyle: {
          backgroundColor: colors.bgCard,
          borderTopColor: colors.border,
          borderTopWidth: 1,
          paddingBottom: 4,
          height: 60,
        },
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.textDim,
        tabBarLabelStyle: { fontSize: 11, fontWeight: '600' },
        tabBarIcon: ({ color, size, focused }) => {
          const icons: Record<string, { outline: string; filled: string }> = {
            Dashboard: { outline: 'home-outline', filled: 'home' },
            Trades: { outline: 'list-outline', filled: 'list' },
            Performance: { outline: 'bar-chart-outline', filled: 'bar-chart' },
            Analisi: { outline: 'pulse-outline', filled: 'pulse' },
            Settings: { outline: 'settings-outline', filled: 'settings' },
          };
          const icon = icons[route.name];
          const name = focused ? icon?.filled : icon?.outline;
          return (
            <View>
              <Ionicons name={(name || 'ellipse-outline') as any} size={size} color={color} />
              {route.name === 'Trades' && <TabBadge count={openTrades.length} />}
            </View>
          );
        },
      })}
    >
      <Tab.Screen name="Dashboard" component={DashboardScreen} options={{ title: 'Dashboard' }} />
      <Tab.Screen name="Trades" component={TradesScreen} options={{ title: 'Trades' }} />
      <Tab.Screen name="Performance" component={PerformanceScreen} options={{ title: 'Performance' }} />
      <Tab.Screen name="Analisi" component={AnalysisScreen} options={{ title: 'Analisi' }} />
      <Tab.Screen name="Settings" component={SettingsScreen} options={{ title: 'Impostazioni' }} />
    </Tab.Navigator>
  );
}

export default function App() {
  return (
    <BotProvider>
      <NavigationContainer theme={navTheme}>
        <StatusBar style="light" />
        <AppTabs />
      </NavigationContainer>
    </BotProvider>
  );
}
