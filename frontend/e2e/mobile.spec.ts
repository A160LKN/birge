import { expect, test } from '@playwright/test';
import { apiCall, lane, openBoard, person, teamBoard } from './helpers';

test('на телефоне колонки листаются, карточка открывается на весь экран', async ({ page }) => {
  const aliya = await person('Алия');
  const board = await teamBoard(aliya);
  await apiCall(aliya, 'post', '/cards', { column_id: board.columns[0]?.id, title: 'Позвонить клиенту' });
  await page.addInitScript(
    (token) => localStorage.setItem('birge.token', JSON.stringify(token)),
    aliya.token,
  );
  await openBoard(page, board.id);

  const pageWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(pageWidth).toBeLessThanOrEqual(page.viewportSize()?.width ?? 0); // страница не уезжает вбок
  await expect(lane(page, 'Нужно сделать')).toBeInViewport();
  await expect(lane(page, 'Готово')).not.toBeInViewport();

  await page.getByText('Позвонить клиенту').click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  // Ждём конца анимации появления — окно на всю ширину экрана
  await expect
    .poll(async () => (await dialog.boundingBox())?.width)
    .toBeGreaterThanOrEqual((page.viewportSize()?.width ?? 0) - 1);
});
