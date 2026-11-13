import { expect, test } from '@playwright/test';
import { apiCall, browserFor, dragCard, lane, openBoard, person, teamBoard } from './helpers';

test.describe('Совместная работа в реальном времени', () => {
  test('карточка, созданная одним, сразу появляется у другого', async ({ browser }) => {
    const aliya = await person('Алия');
    const bauyrzhan = await person('Бауыржан');
    const board = await teamBoard(aliya, bauyrzhan);
    const a = await browserFor(browser, aliya);
    const b = await browserFor(browser, bauyrzhan);
    await openBoard(a, board.id);
    await openBoard(b, board.id);

    await lane(a, 'Нужно сделать').getByRole('button', { name: 'Добавить карточку' }).click();
    await a.getByLabel('Название новой карточки').fill('Подготовить демо');
    await a.getByLabel('Название новой карточки').press('Enter');

    // У Бауыржана — без перезагрузки страницы, с подсветкой цветом Алии
    const arrived = lane(b, 'Нужно сделать').getByTestId('card').filter({ hasText: 'Подготовить демо' });
    await expect(arrived).toBeVisible();
    await expect(arrived.getByText('Алия')).toBeVisible();
    await expect(arrived.getByText('Алия')).toBeHidden({ timeout: 5000 }); // флажок исчезает сам
  });

  test('перетаскивание у одного — карточка переезжает у другого', async ({ browser }) => {
    const aliya = await person('Алия');
    const bauyrzhan = await person('Бауыржан');
    const board = await teamBoard(aliya, bauyrzhan);
    const todo = board.columns[0]?.id ?? 0;
    await apiCall(aliya, 'post', '/cards', { column_id: todo, title: 'Купить домен' });
    await apiCall(aliya, 'post', '/cards', { column_id: todo, title: 'Настроить почту' });

    const a = await browserFor(browser, aliya);
    const b = await browserFor(browser, bauyrzhan);
    await openBoard(a, board.id);
    await openBoard(b, board.id);

    await dragCard(b, 'Купить домен', lane(b, 'Готово'));
    await expect(lane(b, 'Готово').getByText('Купить домен')).toBeVisible();
    await expect(lane(a, 'Готово').getByText('Купить домен')).toBeVisible();
    await expect(lane(a, 'Нужно сделать').getByText('Купить домен')).toHaveCount(0);

    // После перезагрузки порядок тот же — его сохранил сервер, а не только браузер
    await a.reload();
    await expect(lane(a, 'Готово').getByText('Купить домен')).toBeVisible();
  });

  test('видно, кто сейчас на доске', async ({ browser }) => {
    const aliya = await person('Алия');
    const bauyrzhan = await person('Бауыржан');
    const board = await teamBoard(aliya, bauyrzhan);
    const a = await browserFor(browser, aliya);
    await openBoard(a, board.id);
    await expect(a.getByRole('button', { name: 'Участники: 2, сейчас на доске: 1' })).toBeVisible();

    const b = await browserFor(browser, bauyrzhan);
    await openBoard(b, board.id);
    await expect(a.getByRole('button', { name: 'Участники: 2, сейчас на доске: 2' })).toBeVisible();

    await b.context().close();
    await expect(a.getByRole('button', { name: 'Участники: 2, сейчас на доске: 1' })).toBeVisible();
  });

  test('одновременная правка описания — конфликт, а не молчаливая перезапись', async ({ browser }) => {
    const aliya = await person('Алия');
    const bauyrzhan = await person('Бауыржан');
    const board = await teamBoard(aliya, bauyrzhan);
    const card = await apiCall<{ id: number }>(aliya, 'post', '/cards', {
      column_id: board.columns[0]?.id,
      title: 'Договор',
      description: 'Черновик',
    });
    const a = await browserFor(browser, aliya);
    const b = await browserFor(browser, bauyrzhan);
    await a.goto(`/boards/${board.id}?card=${card.id}`);
    await b.goto(`/boards/${board.id}?card=${card.id}`);

    await a.getByRole('dialog').getByRole('button', { name: 'Изменить' }).click(); // Алия начала писать…
    await b.getByRole('dialog').getByRole('button', { name: 'Изменить' }).click();
    await b.getByRole('textbox', { name: 'Описание' }).fill('Версия Бауыржана');
    await b.getByRole('button', { name: 'Сохранить', exact: true }).click(); // …а Бауыржан сохранил раньше
    await expect(b.getByRole('dialog').getByText('Версия Бауыржана')).toBeVisible();

    // Алия ещё пишет — её предупреждают заранее
    await expect(a.getByText('Пока вы писали, карточку изменили')).toBeVisible();
    await a.getByRole('textbox', { name: 'Описание' }).fill('Версия Алии');
    await a.getByRole('button', { name: 'Сохранить', exact: true }).click();
    const alert = a.getByRole('alert');
    await expect(alert).toContainText('Карточку успели изменить до вас');
    await expect(alert).toContainText('Версия Бауыржана');

    await alert.getByRole('button', { name: 'Сохранить мою версию' }).click();
    await expect(a.getByRole('dialog').getByText('Версия Алии')).toBeVisible();
    await expect(b.getByRole('dialog').getByText('Версия Алии')).toBeVisible(); // и у Бауыржана вживую
  });
});
