import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { apiCall, browserFor, openBoard, person, teamBoard } from './helpers';

/** Доступность по WCAG 2.1 AA: контраст, подписи, роли, работа с клавиатуры. */
async function audit(page: Page, name: string) {
  await page.waitForTimeout(300); // тема применяется после загрузки — ждём конца плавной смены цветов
  const { violations } = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();
  const report = violations.map(
    (v) => `${v.id}: ${v.help} (${v.nodes.length})\n  ${v.nodes[0]?.target.join(' ')}`,
  );
  expect(report, `${name}: нарушения доступности`).toEqual([]);
}

for (const scheme of ['light', 'dark'] as const) {
  test(`доступность ключевых экранов — тема ${scheme}`, async ({ browser }) => {
    const alia = await person('Алия');
    const bauyr = await person('Бауыржан');
    const board = await teamBoard(alia, bauyr);
    await apiCall(alia, 'post', '/cards', { column_id: board.columns[0].id, title: 'Проверить доступность' });

    const guestContext = await browser.newContext({ colorScheme: scheme, locale: 'ru-RU' });
    const guest = await guestContext.newPage();
    await guest.goto('/login');
    await expect(guest.getByRole('heading').first()).toBeVisible();
    await audit(guest, 'вход');
    await guest.goto('/register');
    await audit(guest, 'регистрация');

    const page = await browserFor(browser, alia);
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto('/');
    await expect(page.getByRole('heading').first()).toBeVisible();
    await audit(page, 'список досок');
    await openBoard(page, board.id);
    await audit(page, 'доска');
    await page.getByText('Проверить доступность').click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await audit(page, 'карточка');
  });
}
