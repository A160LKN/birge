import createClient, { type Middleware } from 'openapi-fetch';
import { tokenStore } from '@/auth/token';
import { networkError, toApiError } from './errors';
import type { components, paths } from './schema';

export const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000';

/** Ключ этой вкладки: по нему в потоке событий видно, какие изменения сделаны отсюда. */
export const CLIENT_ID = `tab-${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36)}`;

const auth: Middleware = {
  onRequest({ request }) {
    const token = tokenStore.get();
    if (token) request.headers.set('Authorization', `Bearer ${token}`);
    request.headers.set('X-Client-Id', CLIENT_ID);
    return request;
  },
  onResponse({ response }) {
    // Токен истёк или отозван — выходим, а не показываем «полувошедший» интерфейс
    if (response.status === 401 && tokenStore.get()) tokenStore.set(null);
    return response;
  },
};

// fetch берётся в момент запроса, а не при загрузке модуля — иначе моки в тестах его не перехватят
export const api = createClient<paths>({ baseUrl: API_URL, fetch: (request) => globalThis.fetch(request) });
api.use(auth);

/** Вызов API: данные или ApiError. Сетевой сбой — тоже ApiError, с понятным текстом. */
export async function call<T>(
  request: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result: { data?: T; error?: unknown; response: Response };
  try {
    result = await request;
  } catch {
    throw networkError();
  }
  if (!result.response.ok) throw toApiError(result.response.status, result.error);
  return result.data as T;
}

/** Ссылки на файлы приходят относительными и подписанными — добавляем адрес API. */
export const fileUrl = (path: string) => `${API_URL}${path}`;

type Schemas = components['schemas'];
export type User = Schemas['UserOut'];
export type Board = Schemas['BoardOut'];
export type BoardSummary = Schemas['BoardSummary'];
export type Column = Schemas['ColumnOut'];
export type Card = Schemas['CardOut'];
export type CardDetail = Schemas['CardDetail'];
export type Member = Schemas['MemberOut'];
export type Comment = Schemas['CommentOut'];
export type Attachment = Schemas['AttachmentOut'];
export type Activity = Schemas['ActivityOut'];
export type Export = Schemas['ExportOut'];
export type CardPatch = Schemas['CardPatch'];
