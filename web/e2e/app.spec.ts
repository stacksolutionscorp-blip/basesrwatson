import { expect, test, type Page } from "@playwright/test";

const EMAIL = process.env.E2E_EMAIL ?? "admin@demo.com";
const SENHA = process.env.E2E_SENHA ?? "demo-senha-123";
const SHOTS = process.env.E2E_SHOTS; // diretório opcional para capturas de tela

async function shot(page: Page, name: string) {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

async function entrar(page: Page) {
  await page.goto("/");
  await page.getByLabel("E-mail").fill(EMAIL);
  await page.getByLabel("Senha").fill(SENHA);
  await page.getByRole("button", { name: "Entrar" }).click();
  // primeiro acesso: aceite dos termos
  const aceite = page.getByRole("checkbox");
  const ola = page.getByRole("heading", { name: /Olá/ });
  await expect(ola.or(aceite)).toBeVisible();
  if (await aceite.isVisible()) {
    await shot(page, "01-termos");
    await aceite.check();
    await page.getByRole("button", { name: "Aceitar e continuar" }).click();
  }
  await expect(page.getByRole("heading", { name: /Olá/ })).toBeVisible();
}

test.describe.configure({ mode: "serial" });

test("login com senha errada mostra erro", async ({ page }) => {
  await page.goto("/");
  await shot(page, "00-login");
  await page.getByLabel("E-mail").fill(EMAIL);
  await page.getByLabel("Senha").fill("senha-errada-1");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("alert")).toContainText("incorretos");
});

test("busca única → página da empresa", async ({ page }) => {
  await entrar(page);
  await shot(page, "02-inicio");
  await page.getByRole("combobox").fill("pada");
  await expect(page.getByRole("option").first()).toContainText("PADARIA");
  await shot(page, "03-autocomplete");
  await page.getByRole("option", { name: /PADARIA SÃO JOÃO LTDA/ }).first().click();
  await expect(page.getByRole("heading", { name: "PADARIA SÃO JOÃO LTDA" })).toBeVisible();
  await expect(page.getByText("11.222.333/0001-81").first()).toBeVisible();
  await expect(page.getByText("Fabricação de produtos de padaria e confeitaria")).toBeVisible();
  await expect(page.getByRole("link", { name: "JOSÉ DA SILVA" })).toBeVisible();
  await expect(page.getByText("***123456**")).toBeVisible();
  await expect(page.getByTestId("mapa").locator(".leaflet-interactive")).toHaveCount(2); // área + ponto
  await expect(page.getByRole("meter", { name: "Score de risco" })).toBeVisible();
  await shot(page, "04-empresa");
});

test("CNPJ digitado vai direto e DV inválido é avisado", async ({ page }) => {
  await entrar(page);
  await page.getByRole("combobox").fill("11.222.333/0001-82");
  await expect(page.getByText("Dígito verificador do CNPJ não confere.")).toBeVisible();
  await page.getByRole("combobox").fill("12.ABC.345/01DE-35");
  await page.getByRole("combobox").press("Enter");
  await expect(page.getByRole("heading", { name: "EMPRESA ALFANUMÉRICA LTDA" })).toBeVisible();
});

test("grafo societário", async ({ page }) => {
  await entrar(page);
  await page.goto("/grafo/11222333000181");
  await expect(page.getByText(/\d+ nós e \d+ ligações/)).toBeVisible();
  await expect(page.getByTestId("grafo").locator("canvas").first()).toBeVisible();
  await shot(page, "05-grafo");
});

test("busca avançada com mapa e exportação", async ({ page }) => {
  await entrar(page);
  await page.goto("/busca");
  await page.getByRole("button", { name: "SP", exact: true }).click();
  await page.getByRole("button", { name: "Ativa", exact: true }).click();
  await page.getByRole("button", { name: "Buscar" }).click();
  await expect(page.getByRole("link", { name: "PADARIA SÃO JOÃO LTDA" })).toBeVisible();
  await expect(page.getByRole("link", { name: /HOLDING/ })).toHaveCount(0); // baixada
  await expect(page).toHaveURL(/uf=SP/);
  await expect(page.getByTestId("mapa-clusters").locator(".marker-cluster, .leaflet-interactive").first()).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "CSV" }).click();
  expect((await download).suggestedFilename()).toBe("empresas.csv");
  await shot(page, "06-busca");
});

test("sócios", async ({ page }) => {
  await entrar(page);
  await page.goto("/socios?nome=jose%20da%20silva");
  await expect(page.getByText("PADARIA SÃO JOÃO LTDA")).toBeVisible();
  await expect(page.getByText(/HOLDING/)).toBeVisible();
  await shot(page, "07-socios");
});

test("consulta em lote", async ({ page }) => {
  await entrar(page);
  await page.goto("/lote");
  await page.getByLabel("CNPJs").fill("11.222.333/0001-81\n11222333000182\n12.ABC.345/01DE-35");
  await page.getByRole("button", { name: /Consultar 3 CNPJs/ }).click();
  await expect(page.getByText("2 encontrados · 1 com erro")).toBeVisible();
  await shot(page, "08-lote");
});

test("monitoramento", async ({ page }) => {
  await entrar(page);
  await page.goto("/monitoramento");
  await page.getByLabel("Um ou mais CNPJs").fill("11222333000181");
  await page.getByRole("button", { name: "Monitorar" }).click();
  await expect(page.getByRole("link", { name: "11.222.333/0001-81" })).toBeVisible();
  await page.getByRole("button", { name: "Histórico" }).first().click();
  await expect(page.getByText("Nenhuma alteração detectada")).toBeVisible();
  await page.keyboard.press("Escape");
  await shot(page, "09-monitoramento");
});

test("uso da API", async ({ page }) => {
  await entrar(page);
  await page.goto("/uso");
  await expect(page.getByTestId("grafico-uso")).toBeVisible();
  await expect(page.getByText("/v1/cnpj/{cnpj}", { exact: true })).toBeVisible();
  await shot(page, "10-uso");
});

test("administração: chave de API e auditoria", async ({ page }) => {
  await entrar(page);
  await page.goto("/admin");
  await expect(page.getByText(EMAIL)).toBeVisible();
  await page.getByRole("tab", { name: "Chaves de API" }).click();
  await page.getByLabel("Nome da chave").fill("ERP de teste");
  await page.getByRole("button", { name: "Gerar chave" }).click();
  await expect(page.getByTestId("chave-criada")).toContainText("cnpj_");
  await shot(page, "11-admin-chave");
  await page.getByRole("button", { name: "Fechar" }).click();
  await page.getByRole("tab", { name: "Cargas da Receita" }).click();
  await expect(page.getByText("success").first()).toBeVisible();
  await page.getByRole("tab", { name: "Auditoria" }).click();
  await expect(page.getByText("/v1/cnpj/11222333000181").first()).toBeVisible();
  await shot(page, "12-admin-auditoria");
});

test("sair", async ({ page }) => {
  await entrar(page);
  await page.getByRole("button", { name: "Sair" }).click();
  await expect(page.getByRole("button", { name: "Entrar" })).toBeVisible();
});
