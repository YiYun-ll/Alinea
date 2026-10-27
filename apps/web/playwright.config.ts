import { defineConfig } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 300_000,
  expect: { timeout: 30_000 },
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:5173',
    viewport: { width: 1280, height: 720 },
    video: 'on',
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `${process.env.PYTHON ?? 'python'} -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000`,
      cwd: root,
      url: 'http://127.0.0.1:8000/health',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        ALINEA_DATABASE_URL: 'sqlite:///./.data/playwright.db',
        ALINEA_STORAGE_ROOT: './.data/playwright-storage',
        ALINEA_RENDER_TIMEOUT_SECONDS: '120',
        ALINEA_LLM_API_KEY: '',
      },
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5173',
      cwd: path.join(root, 'apps/web'),
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
})
