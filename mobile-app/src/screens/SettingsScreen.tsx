import React, { useState, useEffect } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  ScrollView, Alert, ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { getConfig, saveConfig, testConnection, sendBotCommand, BotConfig } from '../api/freqtradeApi';
import { useBot } from '../context/BotContext';
import { colors } from '../constants/colors';

export function SettingsScreen() {
  const { botRunning, strategy, dryRun, lastUpdate, refresh, profitStats } = useBot();
  const [config, setConfig] = useState<BotConfig>({ baseUrl: '', username: '', password: '' });
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showPass, setShowPass] = useState(false);

  useEffect(() => {
    getConfig().then(setConfig);
  }, []);

  const handleTest = async () => {
    setTesting(true);
    const ok = await testConnection(config);
    setTesting(false);
    Alert.alert(ok ? 'Connesso!' : 'Errore', ok ? 'Connessione al bot riuscita.' : 'Impossibile connettersi. Verifica URL e credenziali.');
  };

  const handleSave = async () => {
    setSaving(true);
    await saveConfig(config);
    await refresh();
    setSaving(false);
    Alert.alert('Salvato', 'Configurazione aggiornata.');
  };

  const handleBotCommand = async (cmd: 'start' | 'stop' | 'reload') => {
    const labels = { start: 'Avviare', stop: 'Fermare', reload: 'Ricaricare' };
    Alert.alert(
      `${labels[cmd]} il bot?`,
      `Confermi di voler ${labels[cmd].toLowerCase()} il bot?`,
      [
        { text: 'Annulla', style: 'cancel' },
        {
          text: 'Conferma',
          style: cmd === 'stop' ? 'destructive' : 'default',
          onPress: async () => {
            try {
              await sendBotCommand(cmd);
              setTimeout(refresh, 2000);
            } catch (e) {
              Alert.alert('Errore', 'Comando fallito.');
            }
          },
        },
      ]
    );
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.title}>Impostazioni</Text>

      {/* Bot status card */}
      <View style={styles.statusCard}>
        <View style={styles.statusRow}>
          <View style={[styles.statusDot, { backgroundColor: botRunning ? colors.green : colors.red }]} />
          <Text style={styles.statusText}>{botRunning ? 'Bot RUNNING' : 'Bot STOPPED'}</Text>
          {dryRun && <View style={styles.dryBadge}><Text style={styles.dryText}>DRY RUN</Text></View>}
        </View>
        <Text style={styles.strategyText}>{strategy}</Text>
        {lastUpdate && (
          <Text style={styles.updateText}>
            Ultimo aggiornamento: {lastUpdate.toLocaleTimeString('it-IT')}
          </Text>
        )}
        {profitStats && (
          <Text style={styles.updateText}>
            Bot attivo dal: {new Date(profitStats.bot_start_date).toLocaleDateString('it-IT')}
          </Text>
        )}
      </View>

      {/* Bot controls */}
      <Text style={styles.sectionTitle}>Controlli bot</Text>
      <View style={styles.controlsRow}>
        <TouchableOpacity
          style={[styles.ctrlBtn, { backgroundColor: colors.greenDim, borderColor: colors.green }]}
          onPress={() => handleBotCommand('start')}
        >
          <Ionicons name="play" size={16} color={colors.green} />
          <Text style={[styles.ctrlText, { color: colors.green }]}>Start</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.ctrlBtn, { backgroundColor: colors.redDim, borderColor: colors.red }]}
          onPress={() => handleBotCommand('stop')}
        >
          <Ionicons name="stop" size={16} color={colors.red} />
          <Text style={[styles.ctrlText, { color: colors.red }]}>Stop</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.ctrlBtn, { backgroundColor: colors.accentDim, borderColor: colors.accent }]}
          onPress={() => handleBotCommand('reload')}
        >
          <Ionicons name="refresh" size={16} color={colors.accent} />
          <Text style={[styles.ctrlText, { color: colors.accent }]}>Reload</Text>
        </TouchableOpacity>
      </View>

      {/* Connection config */}
      <Text style={[styles.sectionTitle, { marginTop: 8 }]}>Connessione server</Text>
      <View style={styles.card}>
        <Text style={styles.fieldLabel}>URL server</Text>
        <TextInput
          style={styles.input}
          value={config.baseUrl}
          onChangeText={v => setConfig(c => ({ ...c, baseUrl: v }))}
          placeholder="http://IP:8080"
          placeholderTextColor={colors.textDim}
          autoCapitalize="none"
          keyboardType="url"
        />

        <Text style={styles.fieldLabel}>Username</Text>
        <TextInput
          style={styles.input}
          value={config.username}
          onChangeText={v => setConfig(c => ({ ...c, username: v }))}
          placeholder="username"
          placeholderTextColor={colors.textDim}
          autoCapitalize="none"
        />

        <Text style={styles.fieldLabel}>Password</Text>
        <View style={styles.passwordRow}>
          <TextInput
            style={[styles.input, { flex: 1, marginBottom: 0 }]}
            value={config.password}
            onChangeText={v => setConfig(c => ({ ...c, password: v }))}
            placeholder="password"
            placeholderTextColor={colors.textDim}
            secureTextEntry={!showPass}
            autoCapitalize="none"
          />
          <TouchableOpacity onPress={() => setShowPass(!showPass)} style={styles.eyeBtn}>
            <Ionicons name={showPass ? 'eye-off' : 'eye'} size={18} color={colors.textSecondary} />
          </TouchableOpacity>
        </View>

        <View style={styles.btnRow}>
          <TouchableOpacity style={styles.testBtn} onPress={handleTest} disabled={testing}>
            {testing ? <ActivityIndicator size="small" color={colors.accent} /> : (
              <>
                <Ionicons name="wifi-outline" size={14} color={colors.accent} />
                <Text style={styles.testBtnText}>Test</Text>
              </>
            )}
          </TouchableOpacity>
          <TouchableOpacity style={styles.saveBtn} onPress={handleSave} disabled={saving}>
            {saving ? <ActivityIndicator size="small" color={colors.bg} /> : (
              <>
                <Ionicons name="save-outline" size={14} color={colors.bg} />
                <Text style={styles.saveBtnText}>Salva</Text>
              </>
            )}
          </TouchableOpacity>
        </View>
      </View>

      {/* App info */}
      <View style={styles.infoCard}>
        <Text style={styles.infoText}>Trading Bot Dashboard v1.0</Text>
        <Text style={styles.infoSub}>Freqtrade API • Hyperliquid • VolatilitySystemTrail</Text>
        <Text style={styles.infoSub}>Refresh automatico ogni 30 secondi</Text>
      </View>

      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  title: { color: colors.text, fontSize: 22, fontWeight: '800', marginBottom: 16 },
  statusCard: { backgroundColor: colors.bgCard, borderRadius: 16, padding: 16, marginBottom: 16, borderWidth: 1, borderColor: colors.border, gap: 6 },
  statusRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  statusDot: { width: 10, height: 10, borderRadius: 5 },
  statusText: { color: colors.text, fontSize: 16, fontWeight: '700' },
  dryBadge: { backgroundColor: colors.yellowDim, paddingHorizontal: 8, paddingVertical: 2, borderRadius: 6 },
  dryText: { color: colors.yellow, fontSize: 10, fontWeight: '700' },
  strategyText: { color: colors.accent, fontSize: 13, fontWeight: '600' },
  updateText: { color: colors.textSecondary, fontSize: 12 },
  sectionTitle: { color: colors.textSecondary, fontSize: 12, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 10 },
  controlsRow: { flexDirection: 'row', gap: 8, marginBottom: 16 },
  ctrlBtn: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, padding: 12, borderRadius: 12, borderWidth: 1 },
  ctrlText: { fontWeight: '700', fontSize: 14 },
  card: { backgroundColor: colors.bgCard, borderRadius: 16, padding: 16, borderWidth: 1, borderColor: colors.border },
  fieldLabel: { color: colors.textSecondary, fontSize: 12, marginBottom: 6, marginTop: 12 },
  input: { backgroundColor: colors.bgCard2, borderRadius: 10, padding: 12, color: colors.text, fontSize: 14, borderWidth: 1, borderColor: colors.border, marginBottom: 4 },
  passwordRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 4 },
  eyeBtn: { padding: 10 },
  btnRow: { flexDirection: 'row', gap: 8, marginTop: 16 },
  testBtn: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, padding: 12, borderRadius: 12, borderWidth: 1, borderColor: colors.accent, backgroundColor: colors.accentDim },
  testBtnText: { color: colors.accent, fontWeight: '700' },
  saveBtn: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, padding: 12, borderRadius: 12, backgroundColor: colors.accent },
  saveBtnText: { color: colors.bg, fontWeight: '700' },
  infoCard: { marginTop: 20, alignItems: 'center', gap: 4, padding: 16 },
  infoText: { color: colors.textSecondary, fontSize: 13, fontWeight: '600' },
  infoSub: { color: colors.textDim, fontSize: 11 },
});
