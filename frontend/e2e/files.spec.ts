import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';
import { apiCall, browserFor, lane, openBoard, person, teamBoard } from './helpers';

// Настоящая PNG-картинка 64×40
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAEAAAAAoCAIAAADBrGu+AAAAT0lEQVR4Xu3RAQkAIQAEQTXQx7SMJeVTLMJMgjt2fvuMl62Xx/8cqClQU6CmQE2BmgI1BWoK1BSoKVBToKZATYGaAjUFagrUFKgpUFOgdgEstwGvRmhz/AAAAABJRU5ErkJggg==',
  'base64',
);

test('картинка: превью готовится в фоне и становится обложкой карточки', async ({ browser }) => {
  const aliya = await person('Алия');
  const board = await teamBoard(aliya);
  const card = await apiCall<{ id: number }>(aliya, 'post', '/cards', {
    column_id: board.columns[0]?.id,
    title: 'Макет',
  });
  const page = await browserFor(browser, aliya);
  await page.goto(`/boards/${board.id}?card=${card.id}`);

  const dialog = page.getByRole('dialog');
  await dialog
    .getByLabel('Прикрепить')
    .setInputFiles({ name: 'макет.png', mimeType: 'image/png', buffer: PNG });
  const attachment = dialog.getByTestId('attachment');
  await expect(attachment.getByRole('link', { name: 'макет.png' })).toBeVisible();
  // Фоновая задача сделала превью — оно пришло по WebSocket, без перезагрузки
  await expect(attachment.locator('img')).toBeVisible({ timeout: 10_000 });

  await dialog.getByRole('button', { name: 'Закрыть' }).click();
  await expect(lane(page, 'Нужно сделать').getByTestId('card').locator('img')).toBeVisible();
});

test('опасный файл не принимается', async ({ browser }) => {
  const aliya = await person('Алия');
  const board = await teamBoard(aliya);
  const card = await apiCall<{ id: number }>(aliya, 'post', '/cards', {
    column_id: board.columns[0]?.id,
    title: 'Лого',
  });
  const page = await browserFor(browser, aliya);
  await page.goto(`/boards/${board.id}?card=${card.id}`);
  await page
    .getByRole('dialog')
    .getByLabel('Прикрепить')
    .setInputFiles({
      name: 'logo.png',
      mimeType: 'image/png',
      buffer: Buffer.from('<svg><script>alert(1)</script></svg>'),
    });
  await expect(page.getByText(/«logo.png»: Такой файл прикрепить нельзя/)).toBeVisible();
});

test('выгрузка в CSV: готовится в фоне, о готовности сообщают, файл скачивается', async ({ browser }) => {
  const aliya = await person('Алия');
  const board = await teamBoard(aliya);
  await apiCall(aliya, 'post', '/cards', { column_id: board.columns[0]?.id, title: 'Купить домен' });
  const page = await browserFor(browser, aliya);
  await openBoard(page, board.id);

  await page.getByRole('button', { name: 'CSV' }).click();
  await expect(page.getByText('Выгрузка доски готова')).toBeVisible({ timeout: 10_000 });
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Скачать' }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/\.csv$/);
  const content = await readFile(await file.path(), 'utf-8');
  expect(content).toContain('Купить домен');
});
