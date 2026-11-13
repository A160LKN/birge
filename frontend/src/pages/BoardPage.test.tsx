import { screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { CLIENT_ID } from '@/api/client';
import { API, appError, board, card, detail, server, socket } from '@/test/server';
import { renderPage } from '@/test/render';
import { BoardPage } from './BoardPage';

const open = (route = '/boards/5') =>
  renderPage(<BoardPage />, { route, path: '/boards/:boardId', loggedIn: true });

/** Сервер отправит событие всем, кто подключён к доске. */
function serverSends(message: object) {
  server.use(
    socket.addEventListener('connection', ({ client }) => {
      client.addEventListener('message', (event) => {
        if ((JSON.parse(event.data as string) as { type: string }).type === 'auth') {
          client.send(JSON.stringify({ type: 'ready', user_id: 1, presence: [1, 2] }));
          setTimeout(() => client.send(JSON.stringify(message)), 20);
        }
      });
    }),
  );
}

const lane = (name: string) => screen.getByRole('region', { name: new RegExp(name) });

it('колонки и карточки по порядку, статус соединения', async () => {
  open();
  expect(await screen.findByText('Сверстать лендинг')).toBeInTheDocument();
  expect(
    within(lane('Нужно сделать'))
      .getAllByTestId('card')
      .map((c) => c.textContent),
  ).toEqual([expect.stringContaining('Сверстать лендинг'), expect.stringContaining('Купить домен')]);
  expect(await screen.findByText('Изменения видны всем сразу')).toBeInTheDocument();
});

it('коллега перенёс карточку — она переезжает и подсвечивается его именем', async () => {
  serverSends({
    type: 'card.moved',
    id: 41,
    board_id: 5,
    actor_id: 2,
    client_id: 'other-tab',
    data: card({ column_id: 12, position: 'z', updated_at: '2026-11-13T09:00:00Z' }),
  });
  open();
  await waitFor(() => expect(within(lane('Готово')).queryByText('Сверстать лендинг')).toBeInTheDocument());
  expect(within(lane('Готово')).getByText('Бауыржан')).toBeInTheDocument(); // флажок с именем
});

it('своё изменение из этой вкладки не подсвечивается', async () => {
  serverSends({
    type: 'card.updated',
    id: 41,
    board_id: 5,
    actor_id: 1,
    client_id: CLIENT_ID,
    data: card({ title: 'Моё', version: 2 }),
  });
  open();
  expect(await screen.findByText('Моё')).toBeInTheDocument();
  expect(screen.queryByText('Алия', { selector: 'span[aria-hidden]' })).not.toBeInTheDocument();
});

it('доска не найдена', async () => {
  server.use(http.get(`${API}/boards/:id`, () => appError(404, 'not_found', 'Доска не найдена')));
  open();
  expect(await screen.findByText('Доска не найдена')).toBeInTheDocument();
});

it('новая карточка добавляется в колонку', async () => {
  server.use(
    http.post(`${API}/cards`, () =>
      HttpResponse.json(card({ id: 9, title: 'Подключить оплату', position: 'z' }), { status: 201 }),
    ),
  );
  const { user } = open();
  await screen.findByText('Сверстать лендинг');
  await user.click(within(lane('Нужно сделать')).getByRole('button', { name: /Добавить карточку/ }));
  await user.type(screen.getByLabelText('Название новой карточки'), 'Подключить оплату{Enter}');
  expect(await within(lane('Нужно сделать')).findByText('Подключить оплату')).toBeInTheDocument();
});

describe('карточка', () => {
  it('открывается по ссылке ?card= и показывает обсуждение', async () => {
    server.use(
      http.get(`${API}/cards/:id`, () =>
        HttpResponse.json(
          detail({
            comment_list: [
              {
                id: 1,
                card_id: 1,
                body: 'Когда готово?',
                author: { id: 2, name: 'Бауыржан', email: 'b@t.kz' },
                created_at: '2026-11-13T08:00:00Z',
              },
            ],
          }),
        ),
      ),
    );
    open('/boards/5?card=1');
    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText('Когда готово?')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('Название карточки')).toHaveValue('Сверстать лендинг');
  });

  it('конфликт правок: показывает сохранённую версию и даёт выбрать', async () => {
    let patches = 0;
    server.use(
      http.get(`${API}/cards/:id`, () => HttpResponse.json(detail({ description: 'Старое' }))),
      http.patch(`${API}/cards/:id`, async ({ request }) => {
        patches += 1;
        const body = (await request.json()) as { version: number; description: string };
        if (body.version === 1)
          return appError(409, 'version_conflict', 'Карточку уже изменил кто-то другой', {
            current: card({ description: 'Текст Бауыржана', version: 2 }),
          });
        return HttpResponse.json(card({ description: body.description, version: 3 }));
      }),
    );
    const { user } = open('/boards/5?card=1');
    const dialog = await screen.findByRole('dialog');
    await user.click(await within(dialog).findByRole('button', { name: 'Изменить' }));
    const field = within(dialog).getByRole('textbox', { name: 'Описание' });
    await user.clear(field);
    await user.type(field, 'Мой текст');
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить' }));

    const alert = await within(dialog).findByRole('alert');
    expect(alert).toHaveTextContent('Карточку успели изменить до вас');
    expect(alert).toHaveTextContent('Текст Бауыржана');
    expect(field).toHaveValue('Мой текст'); // свой текст не пропал

    await user.click(within(alert).getByRole('button', { name: 'Сохранить мою версию' }));
    await waitFor(() => expect(within(dialog).queryByRole('alert')).not.toBeInTheDocument());
    expect(within(dialog).getByText('Мой текст')).toBeInTheDocument();
    expect(patches).toBe(2);
  });

  it('удалённая карточка', async () => {
    server.use(http.get(`${API}/cards/:id`, () => appError(404, 'not_found', 'Карточка не найдена')));
    open('/boards/5?card=99');
    expect(await screen.findByText(/Карточку удалили/)).toBeInTheDocument();
  });
});

it('участники: владелец приглашает по email', async () => {
  server.use(
    http.post(`${API}/boards/:id/members`, () =>
      HttpResponse.json(
        { user: { id: 3, name: 'Карина', email: 'k@test.kz' }, role: 'member' },
        { status: 201 },
      ),
    ),
  );
  const { user } = open();
  await user.click(await screen.findByRole('button', { name: /Участники: 2/ }));
  const dialog = await screen.findByRole('dialog');
  await user.type(within(dialog).getByLabelText('Пригласить по email'), 'k@test.kz');
  await user.click(within(dialog).getByRole('button', { name: 'Добавить' }));
  expect(await within(dialog).findByText('Карина', { selector: 'strong' })).toBeInTheDocument();
});

it('участник не видит поле приглашения', async () => {
  server.use(http.get(`${API}/boards/:id`, () => HttpResponse.json(board({ role: 'member' }))));
  const { user } = open();
  await user.click(await screen.findByRole('button', { name: /Участники/ }));
  expect(screen.queryByLabelText('Пригласить по email')).not.toBeInTheDocument();
});
