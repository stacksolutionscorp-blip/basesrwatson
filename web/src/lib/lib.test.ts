import { describe, expect, it } from "vitest";
import { qs } from "./api";
import { cleanCnpj, formatCnpj, isValidCnpj, looksLikeCnpj } from "./cnpj";
import { cep, cnae, date, money, phone } from "./format";

describe("cnpj", () => {
  it.each(["11.222.333/0001-81", "11222333000181", "00.000.000/0001-91", "12.ABC.345/01DE-35", "12abc34501de35"])(
    "válido: %s",
    (c) => expect(isValidCnpj(c)).toBe(true),
  );
  it.each(["11.222.333/0001-82", "00000000000000", "1122233300018", "12.ABC.345/01DE-3A", ""])("inválido: %s", (c) =>
    expect(isValidCnpj(c)).toBe(false),
  );
  it("limpa e formata", () => {
    expect(cleanCnpj(" 12.abc.345/01de-35 ")).toBe("12ABC34501DE35");
    expect(formatCnpj("11222333000181")).toBe("11.222.333/0001-81");
  });
  it("reconhece CNPJ digitado na busca", () => {
    expect(looksLikeCnpj("11.222.333/0001-81")).toBe(true);
    expect(looksLikeCnpj("11222333")).toBe(true);
    expect(looksLikeCnpj("padaria são joão")).toBe(false);
  });
});

describe("format", () => {
  it("valores", () => {
    expect(money(1500000.5).replace(/\s/g, " ")).toBe("R$ 1.500.000,50");
    expect(money(null)).toBe("—");
    expect(date("2015-03-10")).toBe("10/03/2015");
    expect(phone("1133334444")).toBe("(11) 3333-4444");
    expect(phone("11933334444")).toBe("(11) 93333-4444");
    expect(cep("01001000")).toBe("01001-000");
    expect(cnae(1091102)).toBe("1091-1/02");
  });
  it("query string ignora vazios e repete listas", () => {
    expect(qs({ uf: ["SP", "RJ"], q: "", cnae: 1, x: null })).toBe("?uf=SP&uf=RJ&cnae=1");
  });
});
