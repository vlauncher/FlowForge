import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30000,
  expect: {
    timeout: 5000,
  },
  use: {
    baseURL: process.env.VITE_API_URL || 'http://localhost:8000',
    trace: 'on-first-retry',
  },
});
