// Мок API для компонентных тестов: тот же контракт, что у настоящего сервера, без сети.
import { http, HttpResponse, ws } from 'msw';
import { setupServer } from 'msw/node';
import type { Board, Card, CardDetail, Member } from '@/api/client';

export const API = 'http://localhost:8000';
export const socket = ws.link('ws://localhost:8000/ws/boards/:id');

export const aliya = { id: 1, email: 'aliya@test.kz', name: 'Алия' };
export const bauyrzhan = { id: 2, email: 'bauyrzhan@test.kz', name: 'Бауыржан' };

export const card = (overrides: Partial<Card> = {}): Card => ({
  id: 1,
  column_id: 10,
  title: 'Сверстать лендинг',
  description: '',
  position: 'V',
  assignee_id: null,
  due_date: null,
  version: 1,
  comments: 0,
  attachments: 0,
  cover_url: null,
  updated_at: '2026-11-13T08:00:00Z',
  ...overrides,
});

export const member = (user: Member['user'], role: Member['role'] = 'member'): Member => ({ user, role });

export const board = (overrides: Partial<Board> = {}): Board => ({
  id: 5,
  title: 'Запуск',
  role: 'owner',
  members: [member(aliya, 'owner'), member(bauyrzhan)],
  columns: [
    { id: 10, title: 'Нужно сделать', position: 'V' },
    { id: 11, title: 'В работе', position: 'k' },
    { id: 12, title: 'Готово', position: 's' },
  ],
  cards: [card(), card({ id: 2, title: 'Купить домен', position: 'k', assignee_id: 2, comments: 3 })],
  last_event_id: 40,
  ...overrides,
});

export const detail = (overrides: Partial<CardDetail> = {}): CardDetail => ({
  ...card(),
  created_at: '2026-11-13T08:00:00Z',
  created_by: 1,
  comment_list: [],
  attachment_list: [],
  ...overrides,
});

export const server = setupServer(
  http.get(`${API}/auth/me`, () => HttpResponse.json(aliya)),
  http.get(`${API}/boards`, () => HttpResponse.json([])),
  http.get(`${API}/boards/:id`, () => HttpResponse.json(board())),
  // По умолчанию сокет принимает авторизацию и отвечает ready — тесты добавляют свои сообщения
  socket.addEventListener('connection', ({ client }) => {
    client.addEventListener('message', (event) => {
      const message = JSON.parse(event.data as string) as { type: string };
      if (message.type === 'auth') client.send(JSON.stringify({ type: 'ready', user_id: 1, presence: [1] }));
    });
  }),
);

export const appError = (status: number, code: string, message: string, details?: unknown) =>
  HttpResponse.json({ error: { code, message, ...(details ? { details } : {}) } }, { status });
