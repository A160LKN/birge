/**
 * События доски из WebSocket и их применение к данным в кеше.
 *
 * Функции чистые: принимают старое состояние и событие, возвращают новое. Поэтому их легко
 * проверить юнит-тестами, а применение события дважды ничего не ломает (идемпотентность).
 */
import type {
  Activity,
  Attachment,
  Board,
  Card,
  CardDetail,
  Column,
  Comment,
  Export,
  Member,
} from '@/api/client';

interface Base {
  id: number;
  board_id: number;
  actor_id: number | null;
  client_id: string | null;
}

type WithActivity<T> = T & { activity?: Activity };

export type BoardEvent = Base &
  (
    | { type: 'board.updated'; data: WithActivity<{ title: string }> }
    | { type: 'board.deleted'; data: object }
    | { type: 'member.added'; data: WithActivity<Member> }
    | { type: 'member.removed'; data: WithActivity<{ user_id: number; unassigned: number[] }> }
    | { type: 'column.created' | 'column.updated'; data: WithActivity<Column> }
    | { type: 'column.deleted'; data: WithActivity<{ id: number }> }
    | { type: 'card.created' | 'card.updated' | 'card.moved'; data: WithActivity<Card> }
    | { type: 'card.deleted'; data: WithActivity<{ id: number; column_id: number }> }
    | { type: 'comment.created'; data: WithActivity<Comment> }
    | { type: 'attachment.created' | 'attachment.updated'; data: WithActivity<Attachment> }
    | { type: 'attachment.deleted'; data: WithActivity<{ id: number; card_id: number }> }
    | { type: 'export.updated'; data: Export }
  );

export type ServerMessage =
  | BoardEvent
  | { type: 'ready'; user_id: number; presence: number[] }
  | { type: 'presence'; users: number[] }
  | { type: 'resync' }
  | { type: 'pong' }
  | { type: 'error'; code: string; message: string };

const upsert = <T extends { id: number }>(items: T[], item: T): T[] =>
  items.some((x) => x.id === item.id) ? items.map((x) => (x.id === item.id ? item : x)) : [...items, item];

/** Входящая версия карточки не старее той, что уже есть (события и ответы API могут прийти в любом порядке). */
const isFresh = (incoming: Card, current: Card | undefined) =>
  !current ||
  incoming.version > current.version ||
  (incoming.version === current.version && incoming.updated_at >= current.updated_at);

function patchCard(board: Board, id: number, change: (card: Card) => Card): Board {
  return { ...board, cards: board.cards.map((c) => (c.id === id ? change(c) : c)) };
}

export function applyToBoard(board: Board, event: BoardEvent): Board {
  switch (event.type) {
    case 'board.updated':
      return { ...board, title: event.data.title };
    case 'member.added': {
      const { activity: _, ...member } = event.data;
      return board.members.some((m) => m.user.id === member.user.id)
        ? board
        : { ...board, members: [...board.members, member] };
    }
    case 'member.removed': {
      const unassigned = new Set(event.data.unassigned);
      return {
        ...board,
        members: board.members.filter((m) => m.user.id !== event.data.user_id),
        // Сервер снял исполнителя и увеличил версию этих карточек — повторяем то же самое
        cards: board.cards.map((c) =>
          unassigned.has(c.id) && c.assignee_id !== null
            ? { ...c, assignee_id: null, version: c.version + 1 }
            : c,
        ),
      };
    }
    case 'column.created':
    case 'column.updated': {
      const { activity: _, ...column } = event.data;
      return { ...board, columns: upsert(board.columns, column) };
    }
    case 'column.deleted':
      return {
        ...board,
        columns: board.columns.filter((c) => c.id !== event.data.id),
        cards: board.cards.filter((c) => c.column_id !== event.data.id),
      };
    case 'card.created':
    case 'card.updated':
    case 'card.moved': {
      const { activity: _, ...card } = event.data;
      if (!board.columns.some((c) => c.id === card.column_id)) return board;
      const current = board.cards.find((c) => c.id === card.id);
      return isFresh(card, current) ? { ...board, cards: upsert(board.cards, card) } : board;
    }
    case 'card.deleted':
      return { ...board, cards: board.cards.filter((c) => c.id !== event.data.id) };
    case 'comment.created':
      return patchCard(board, event.data.card_id, (c) => ({ ...c, comments: c.comments + 1 }));
    case 'attachment.created':
      return patchCard(board, event.data.card_id, (c) => ({ ...c, attachments: c.attachments + 1 }));
    case 'attachment.deleted':
      return patchCard(board, event.data.card_id, (c) => ({
        ...c,
        attachments: Math.max(0, c.attachments - 1),
      }));
    default:
      return board;
  }
}

/** Открытая карточка: комментарии, вложения и поля обновляются вживую. */
export function applyToCard(card: CardDetail, event: BoardEvent): CardDetail {
  switch (event.type) {
    case 'card.updated':
    case 'card.moved': {
      if (event.data.id !== card.id || !isFresh(event.data, card)) return card;
      const { activity: _, ...fields } = event.data;
      return { ...card, ...fields };
    }
    case 'comment.created': {
      if (event.data.card_id !== card.id || card.comment_list.some((c) => c.id === event.data.id))
        return card;
      const { activity: _, ...comment } = event.data;
      return { ...card, comment_list: [...card.comment_list, comment], comments: card.comments + 1 };
    }
    case 'attachment.created':
    case 'attachment.updated': {
      if (event.data.card_id !== card.id) return card;
      const { activity: _, ...attachment } = event.data;
      const isNew = !card.attachment_list.some((a) => a.id === attachment.id);
      return {
        ...card,
        attachment_list: upsert(card.attachment_list, attachment),
        attachments: card.attachments + (isNew ? 1 : 0),
      };
    }
    case 'attachment.deleted': {
      if (event.data.card_id !== card.id || !card.attachment_list.some((a) => a.id === event.data.id))
        return card;
      return {
        ...card,
        attachment_list: card.attachment_list.filter((a) => a.id !== event.data.id),
        attachments: Math.max(0, card.attachments - 1),
      };
    }
    default:
      return card;
  }
}

/** Какую карточку затрагивает событие — чтобы обновить её, если она открыта. */
export function cardOf(event: BoardEvent): number | null {
  switch (event.type) {
    case 'card.updated':
    case 'card.moved':
    case 'card.created':
      return event.data.id;
    case 'comment.created':
    case 'attachment.created':
    case 'attachment.updated':
    case 'attachment.deleted':
      return event.data.card_id;
    default:
      return null;
  }
}

/** Лента действий: новое — сверху, без повторов. */
export function applyToActivity(feed: Activity[], event: BoardEvent): Activity[] {
  const entry = 'activity' in event.data ? event.data.activity : undefined;
  if (!entry || feed.some((a) => a.id === entry.id)) return feed;
  return [entry, ...feed];
}
