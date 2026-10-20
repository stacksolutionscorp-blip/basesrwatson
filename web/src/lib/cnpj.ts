// Mesma regra de libs/cnpj_core/src/cnpj_core/cnpj.py: CNPJ numérico e alfanumérico (IN RFB 2.229/2024).

const W1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
const W2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];

export function cleanCnpj(value: string): string {
  return value.replace(/[^0-9A-Za-z]/g, "").toUpperCase();
}

function digit(chars: string, weights: number[]): number {
  let total = 0;
  for (let i = 0; i < weights.length; i++) total += (chars.charCodeAt(i) - 48) * weights[i];
  const rest = total % 11;
  return rest < 2 ? 0 : 11 - rest;
}

export function isValidCnpj(value: string): boolean {
  const c = cleanCnpj(value);
  if (!/^[0-9A-Z]{12}[0-9]{2}$/.test(c)) return false;
  if (new Set(c).size === 1) return false;
  const d1 = digit(c, W1);
  const d2 = digit(c.slice(0, 12) + d1, W2);
  return c.slice(12) === `${d1}${d2}`;
}

export function formatCnpj(value: string): string {
  const c = cleanCnpj(value);
  if (c.length !== 14) return value;
  return `${c.slice(0, 2)}.${c.slice(2, 5)}.${c.slice(5, 8)}/${c.slice(8, 12)}-${c.slice(12)}`;
}

/** Parece um CNPJ (completo ou raiz) digitado na busca? */
export function looksLikeCnpj(value: string): boolean {
  const c = cleanCnpj(value);
  return (c.length === 14 || c.length === 8) && /\d/.test(c) && !/\s{2,}/.test(value) && !/[a-z]{4,}/i.test(value);
}
