import { defineConfig, devices } from "@playwright/test";

// Requer a stack rodando (API + front). Variáveis:
//   E2E_BASE_URL   (padrão http://localhost:4173)
//   E2E_EMAIL / E2E_SENHA  usuário admin para o teste
//   PW_CHROMIUM    caminho de um Chromium já instalado (opcional)
export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:4173",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
    launchOptions: process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {},
  },
});
