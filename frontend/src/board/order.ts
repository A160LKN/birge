/** Порядок карточек на доске и расчёт переноса — чистые функции, проверяются юнит-тестами. */
import type { Board, Card } from '@/api/client';
import { compareKeys, keyBetween } from '@/lib/positions';

export type Lanes = Record<number, number[]>;

const byPosition = (a: Card, b: Card) => compareKeys(a.position, b.position) || a.id - b.id;

/** Карточки по колонкам в порядке позиций (при равных ключах — по id, как на сервере). */
export function lanesOf(board: Board): Lanes {
  const lanes: Lanes = Object.fromEntries(board.columns.map((c) => [c.id, [] as number[]]));
  for (const card of [...board.cards].sort(byPosition)) lanes[card.column_id]?.push(card.id);
  return lanes;
}

export function columnsInOrder(board: Board) {
  return [...board.columns].sort((a, b) => compareKeys(a.position, b.position) || a.id - b.id);
}

/** Перенести карточку в колонку на место index (среди остальных карточек этой колонки). */
export function moveInLanes(lanes: Lanes, cardId: number, toColumn: number, index: number): Lanes {
  const next: Lanes = {};
  for (const [column, ids] of Object.entries(lanes)) next[Number(column)] = ids.filter((id) => id !== cardId);
  const target = next[toColumn] ?? [];
  const at = Math.max(0, Math.min(index, target.length));
  next[toColumn] = [...target.slice(0, at), cardId, ...target.slice(at)];
  return next;
}

export function findColumn(lanes: Lanes, cardId: number): number | undefined {
  for (const [column, ids] of Object.entries(lanes)) if (ids.includes(cardId)) return Number(column);
  return undefined;
}

/**
 * Что отправить на сервер и как сразу обновить доску у себя: карточка встаёт после соседа сверху
 * (after_id) и получает ключ между соседями — тем же алгоритмом, что на сервере.
 */
export function planMove(board: Board, lanes: Lanes, cardId: number) {
  const column = findColumn(lanes, cardId);
  if (column === undefined) return null;
  const ids = lanes[column] ?? [];
  const index = ids.indexOf(cardId);
  const byId = new Map(board.cards.map((c) => [c.id, c]));
  const before = index > 0 ? byId.get(ids[index - 1] ?? -1) : undefined;
  const after = byId.get(ids[index + 1] ?? -1);
  const card = byId.get(cardId);
  if (!card) return null;
  if (card.column_id === column && sameNeighbours(board, card, before, after)) return null; // ничего не поменялось
  let position: string;
  try {
    position = keyBetween(before?.position ?? null, after?.position ?? null);
  } catch {
    position = card.position; // соседи с равными ключами — точную позицию выдаст сервер
  }
  return {
    request: { column_id: column, after_id: before?.id ?? null },
    optimistic: { ...card, column_id: column, position },
  };
}

function sameNeighbours(board: Board, card: Card, before: Card | undefined, after: Card | undefined) {
  const ids = lanesOf(board)[card.column_id] ?? [];
  const index = ids.indexOf(card.id);
  return (
    (ids[index - 1] ?? null) === (before?.id ?? null) && (ids[index + 1] ?? null) === (after?.id ?? null)
  );
}
