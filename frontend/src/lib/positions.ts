/**
 * Дробные ключи позиций — тот же алгоритм, что в бэкенде (app/positions.py).
 * Нужен для мгновенного перетаскивания: карточка встаёт на место сразу, ещё до ответа сервера.
 * Совпадение с сервером проверяет тест на общих примерах.
 */
export const DIGITS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';
const ZERO = '0';
const index = (ch: string) => DIGITS.indexOf(ch);

function midpoint(low: string, high: string | null): string {
  if (high !== null) {
    let n = 0;
    while ((low[n] ?? ZERO) === high[n]) n += 1;
    if (n > 0) return high.slice(0, n) + midpoint(low.slice(n), high.slice(n));
  }
  const digitLow = low ? index(low.charAt(0)) : 0;
  const digitHigh = high !== null ? index(high.charAt(0)) : DIGITS.length;
  if (digitHigh - digitLow > 1) return DIGITS.charAt(Math.floor((digitLow + digitHigh + 1) / 2));
  if (high !== null && high.length > 1) return high.charAt(0);
  return DIGITS.charAt(digitLow) + midpoint(low.slice(1), null);
}

/** Ключ между before и after (null — край списка). Ключи сравниваются как строки побайтно. */
export function keyBetween(before: string | null, after: string | null): string {
  if (before !== null && after !== null && before >= after) {
    throw new Error(`Ключи не по порядку: ${before} >= ${after}`);
  }
  return midpoint(before ?? '', after);
}

/** Сравнение ключей как в PostgreSQL с COLLATE "C" (а не localeCompare). */
export const compareKeys = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);
