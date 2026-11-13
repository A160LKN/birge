/** У каждого участника свой цвет — им подсвечиваются аватар и его изменения на доске. */
export const PEOPLE_COLORS = [
  '#e4572e', // киноварь
  '#2e86ab', // стальной синий
  '#a23b72', // слива
  '#d48a00', // янтарь
  '#3b8b5a', // зелень
  '#6c4ab6', // фиолетовый
  '#00897b', // бирюза
  '#c2185b', // малина
];

/** Цвет зависит только от id — у человека он одинаковый на всех досках и у всех коллег. */
export const personColor = (userId: number) =>
  PEOPLE_COLORS[(userId - 1) % PEOPLE_COLORS.length] ?? '#5a6273';

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  // «Алия Сейткали» → «АС», «Алия» → «А»
  const letters = parts.length > 1 ? (parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '') : (parts[0]?.[0] ?? '?');
  return letters.toUpperCase();
}
