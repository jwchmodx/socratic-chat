import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 60_000,  // 다단계 테스트를 위해 여유있게
  expect: { timeout: 10_000 },
  use: {
    baseURL: 'http://localhost:8001',  // 테스트용 포트
    headless: true,
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
  webServer: {
    command: 'TEST_MODE=true PORT=8001 python3 app.py',
    port: 8001,
    reuseExistingServer: true,
    timeout: 10_000,
  },
});
