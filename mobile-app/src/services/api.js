import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';
import Constants from 'expo-constants';

// Use API URL from app.json extra config, fallback to localhost
const API_URL = Constants.expoConfig?.extra?.apiUrl || 'http://localhost:8001';

const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add token to requests
api.interceptors.request.use(
  async (config) => {
    const token = await AsyncStorage.getItem('token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

export const authAPI = {
  register: async (email, username, password) => {
    const response = await api.post('/register', {
      email,
      username,
      password,
    });
    return response.data;
  },

  login: async (username, password) => {
    const response = await api.post('/login', {
      username,
      password,
    });
    if (response.data.access_token) {
      await AsyncStorage.setItem('token', response.data.access_token);
    }
    return response.data;
  },

  logout: async () => {
    await AsyncStorage.removeItem('token');
  },

  getMe: async () => {
    const response = await api.get('/me');
    return response.data;
  },
};

export const exchangeAPI = {
  addKey: async (exchangeName, apiKey, apiSecret) => {
    const response = await api.post('/exchange-keys', {
      exchange_name: exchangeName,
      api_key: apiKey,
      api_secret: apiSecret,
    });
    return response.data;
  },

  getKeys: async () => {
    const response = await api.get('/exchange-keys');
    return response.data;
  },

  deleteKey: async (keyId) => {
    const response = await api.delete(`/exchange-keys/${keyId}`);
    return response.data;
  },
};

export const botAPI = {
  getConfig: async () => {
    const response = await api.get('/bot-config');
    return response.data;
  },

  updateConfig: async (config) => {
    const response = await api.put('/bot-config', config);
    return response.data;
  },
};

export default api;
