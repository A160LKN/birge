import { expect, type Browser, type Page, request } from '@playwright/test';

export const API_URL = process.env.API_URL ?? 'http://localhost:8000';
export const PASSWORD = 'e2e-password-123';

let counter = 0;
export const uniqueEmail = (name: string) =>
  `${name}-${Date.now()}-${counter++}-${Math.random().toString(36).slice(2, 6)}@e2e.kz`;

export interface Person {
  id: number;
  name: string;
  email: string;
  token: string;
}

/** Регистрация через API — быстрее, чем через форму, а форму проверяет отдельный тест. */
export async function person(name: string): Promise<Person> {
  const api = await request.newContext({ baseURL: API_URL });
  const email = uniqueEmail(name.toLowerCase());
  const response = await api.post('/auth/register', { data: { email, name, password: PASSWORD } });
  expect(response.status()).toBe(201);
  const body = (await response.json()) as { access_token: string; user: { id: number } };
  await api.dispose();
  return { id: body.user.id, name, email, token: body.access_token };
}

export async function apiCall<T>(
  who: Person,
  method: 'get' | 'post' | 'patch' | 'delete',
  url: string,
  data?: object,
): Promise<T> {
  const api = await request.newContext({
    baseURL: API_URL,
    extraHTTPHeaders: { Authorization: `Bearer ${who.token}` },
  });
  const response = await api[method](url, data ? { data } : undefined);
  expect(
    response.ok(),
    `${method.toUpperCase()} ${url}: ${response.status()} ${await response.text()}`,
  ).toBeTruthy();
  const body = response.status() === 204 ? null : ((await response.json()) as T);
  await api.dispose();
  return body as T;
}

export interface BoardInfo {
  id: number;
  columns: { id: number; title: string }[];
}

/** Доска владельца с участником — как будто команда уже собрана. */
export async function teamBoard(owner: Person, ...members: Person[]): Promise<BoardInfo> {
  const board = await apiCall<BoardInfo>(owner, 'post', '/boards', { title: `Релиз ${Date.now()}` });
  for (const member of members)
    await apiCall(owner, 'post', `/boards/${board.id}/members`, { email: member.email });
  return board;
}

/** Отдельный браузер со своим входом: токен кладётся туда же, куда его кладёт приложение. */
export async function browserFor(
  browser: Browser,
  who: Person,
  viewport = { width: 1280, height: 800 },
): Promise<Page> {
  const context = await browser.newContext({ viewport, locale: 'ru-RU', timezoneId: 'Asia/Almaty' });
  await context.addInitScript(
    (token) => localStorage.setItem('birge.token', JSON.stringify(token)),
    who.token,
  );
  return context.newPage();
}

export const lane = (page: Page, title: string) => page.getByRole('region', { name: new RegExp(title) });

export async function openBoard(page: Page, boardId: number) {
  await page.goto(`/boards/${boardId}`);
  await expect(page.getByTestId('connection')).toHaveText('Изменения видны всем сразу');
}

/** Перетащить карточку мышью так, как это делает человек: нажать, сдвинуть, отпустить над целью. */
export async function dragCard(page: Page, title: string, target: ReturnType<typeof lane>) {
  const card = page.getByTestId('card').filter({ hasText: title });
  const from = await card.boundingBox();
  const to = await target.boundingBox();
  if (!from || !to) throw new Error('Нет координат для перетаскивания');
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(from.x + from.width / 2 + 10, from.y + from.height / 2 + 10, { steps: 4 });
  await page.mouse.move(to.x + to.width / 2, to.y + 90, { steps: 12 });
  await page.mouse.up();
}
