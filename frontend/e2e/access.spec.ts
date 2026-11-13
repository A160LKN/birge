import { expect, test } from '@playwright/test';
import { apiCall, browserFor, lane, openBoard, PASSWORD, person, teamBoard, uniqueEmail } from './helpers';

test('регистрация через форму и первая доска', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/login\?next=%2F/);
  await page.getByRole('link', { name: 'Зарегистрироваться' }).click();
  await page.getByLabel('Как вас зовут').fill('Айбол');
  await page.getByLabel('Email').fill(uniqueEmail('aibol'));
  await page.getByLabel('Пароль').fill(PASSWORD);
  await page.getByRole('button', { name: 'Создать аккаунт' }).click();

  await page.getByLabel('Название новой доски').fill('Мой проект');
  await page.getByRole('button', { name: 'Создать доску' }).click();
  await expect(page.getByLabel('Название доски')).toHaveValue('Мой проект');
  await expect(page.getByRole('heading', { name: /Нужно сделать/ })).toBeVisible();
});

test('удалённого участника сразу выводит с доски', async ({ browser }) => {
  const aliya = await person('Алия');
  const bauyrzhan = await person('Бауыржан');
  const board = await teamBoard(aliya, bauyrzhan);
  const b = await browserFor(browser, bauyrzhan);
  await openBoard(b, board.id);

  await apiCall(aliya, 'delete', `/boards/${board.id}/members/${bauyrzhan.id}`);
  await expect(b.getByText(/Вас удалили с доски/)).toBeVisible();
  await expect(b).toHaveURL(/\/$/);
});

test('чужую доску по ссылке не открыть', async ({ browser }) => {
  const aliya = await person('Алия');
  const stranger = await person('Чужой');
  const board = await teamBoard(aliya);
  const page = await browserFor(browser, stranger);
  await page.goto(`/boards/${board.id}`);
  await expect(page.getByText('Доска не найдена')).toBeVisible();
});

test('владелец приглашает участника, и тот видит доску', async ({ browser }) => {
  const aliya = await person('Алия');
  const karina = await person('Карина');
  const board = await teamBoard(aliya);
  const a = await browserFor(browser, aliya);
  await openBoard(a, board.id);
  await a.getByRole('button', { name: /Участники: 1/ }).click();
  const dialog = a.getByRole('dialog');
  await dialog.getByLabel('Пригласить по email').fill(karina.email);
  await dialog.getByRole('button', { name: 'Добавить', exact: true }).click();
  await expect(a.getByText('Карина теперь на доске')).toBeVisible();

  const k = await browserFor(browser, karina);
  await openBoard(k, board.id);
  await expect(lane(k, 'Нужно сделать')).toBeVisible();
});
