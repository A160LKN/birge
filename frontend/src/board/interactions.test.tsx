import { screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { App } from '@/App';
import { tokenStore } from '@/auth/token';
import { renderPage } from '@/test/render';
import { API, bauyrzhan, card, detail, server, socket } from '@/test/server';
import { BoardPage } from '@/pages/BoardPage';
import { ApiError } from '@/api/errors';
import type { Attachment } from '@/api/client';

// Загрузка идёт через XMLHttpRequest ради прогресса; сам запрос проверяют E2E-тесты в браузере
const upload = vi.hoisted(() => ({ fn: vi.fn() }));
vi.mock('@/api/upload', () => ({ uploadFile: upload.fn }));

const open = (route = '/boards/5') =>
  renderPage(<BoardPage />, { route, path: '/boards/:boardId', loggedIn: true });
const lane = (name: string) => screen.getByRole('region', { name: new RegExp(name) });

function socketThen(
  send: (client: { send: (data: string) => void; close: (code?: number) => void }) => void,
) {
  server.use(
    socket.addEventListener('connection', ({ client }) => {
      client.addEventListener('message', (event) => {
        if ((JSON.parse(event.data as string) as { type: string }).type === 'auth') {
          client.send(JSON.stringify({ type: 'ready', user_id: 1, presence: [1] }));
          setTimeout(() => send(client), 20);
        }
      });
    }),
  );
}

describe('приложение', () => {
  it('гость попадает на вход, а потом обратно', async () => {
    renderPage(<App />, { route: '/boards/5' });
    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent('/login?next=%2Fboards%2F5'),
    );
  });

  it('несуществующая страница', async () => {
    renderPage(<App />, { route: '/nope', loggedIn: true });
    expect(await screen.findByText('Такой страницы нет')).toBeInTheDocument();
  });

  it('шапка: тема и выход', async () => {
    const { user } = renderPage(<App />, { route: '/', loggedIn: true });
    await user.click(await screen.findByRole('button', { name: 'Тёмная тема' }));
    expect(document.documentElement.dataset.theme).toBe('dark');
    await user.click(screen.getByRole('button', { name: 'Выйти' }));
    expect(tokenStore.get()).toBeNull();
  });
});

describe('колонки', () => {
  it('переименование, сдвиг и удаление через меню', async () => {
    const calls: string[] = [];
    server.use(
      http.patch(`${API}/columns/:id`, async ({ request }) => {
        const { title } = (await request.json()) as { title: string };
        calls.push(`rename:${title}`);
        return HttpResponse.json({ id: 10, title, position: 'V' });
      }),
      http.post(`${API}/columns/:id/move`, async ({ request }) => {
        calls.push(`move:${JSON.stringify(await request.json())}`);
        return HttpResponse.json({ id: 10, title: 'Бэклог', position: 'm' });
      }),
      http.delete(`${API}/columns/:id`, () => {
        calls.push('delete');
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { user } = open();
    await screen.findByText('Сверстать лендинг');

    await user.click(screen.getByRole('button', { name: 'Действия с колонкой «Нужно сделать»' }));
    await user.click(screen.getByRole('button', { name: 'Переименовать' }));
    const input = screen.getByLabelText('Название колонки');
    await user.clear(input);
    await user.type(input, 'Бэклог{Enter}');
    expect(await screen.findByRole('heading', { name: /Бэклог/ })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Действия с колонкой «Бэклог»' }));
    await user.click(screen.getByRole('button', { name: 'Сдвинуть правее' }));
    await user.click(screen.getByRole('button', { name: 'Действия с колонкой «Бэклог»' }));
    await user.click(screen.getByRole('button', { name: 'Удалить колонку' }));
    await waitFor(() => expect(screen.queryByRole('heading', { name: /Бэклог/ })).not.toBeInTheDocument());
    expect(confirm).toHaveBeenCalledWith('Удалить колонку «Бэклог»? Вместе с ней удалятся карточки: 2.');
    expect(calls).toEqual(['rename:Бэклог', 'move:{"after_id":11}', 'delete']);
  });

  it('новая колонка', async () => {
    server.use(
      http.post(`${API}/boards/:id/columns`, () =>
        HttpResponse.json({ id: 13, title: 'Тесты', position: 'v' }, { status: 201 }),
      ),
    );
    const { user } = open();
    await screen.findByText('Сверстать лендинг');
    await user.type(screen.getByLabelText('Новая колонка'), 'Тесты{Enter}');
    expect(await screen.findByRole('heading', { name: /Тесты/ })).toBeInTheDocument();
  });
});

describe('карточка: поля, комментарии, файлы', () => {
  it('исполнитель, комментарий и удаление файла', async () => {
    const attachment = {
      id: 7,
      card_id: 1,
      filename: 'макет.png',
      content_type: 'image/png',
      size: 2048,
      thumbnail: 'ready' as const,
      uploader_id: 1,
      created_at: '',
      url: '/attachments/7/file?sig=x',
      thumbnail_url: '/attachments/7/thumbnail?sig=x',
    };
    server.use(
      http.get(`${API}/cards/:id`, () =>
        HttpResponse.json(detail({ attachment_list: [attachment], attachments: 1 })),
      ),
      http.patch(`${API}/cards/:id`, async ({ request }) => {
        const body = (await request.json()) as { assignee_id: number };
        return HttpResponse.json(card({ assignee_id: body.assignee_id, version: 2 }));
      }),
      http.post(`${API}/cards/:id/comments`, () =>
        HttpResponse.json(
          { id: 3, card_id: 1, body: 'Готово', author: bauyrzhan, created_at: new Date().toISOString() },
          { status: 201 },
        ),
      ),
      http.delete(`${API}/attachments/:id`, () => new HttpResponse(null, { status: 204 })),
    );
    const { user } = open('/boards/5?card=1');
    const dialog = await screen.findByRole('dialog');

    await user.selectOptions(await within(dialog).findByLabelText('Исполнитель'), 'Бауыржан');
    await waitFor(() => expect(within(dialog).getByLabelText('Исполнитель')).toHaveValue('2'));

    await user.type(within(dialog).getByLabelText('Новый комментарий'), 'Готово');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить' }));
    expect(await within(dialog).findByText('Готово', { selector: 'p' })).toBeInTheDocument();

    expect(within(dialog).getByText('2 КБ')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Удалить макет.png' }));
    await waitFor(() => expect(within(dialog).queryByText('макет.png')).not.toBeInTheDocument());
  });

  it('загрузка файла с прогрессом', async () => {
    server.use(http.get(`${API}/cards/:id`, () => HttpResponse.json(detail())));
    upload.fn.mockImplementation((_card: number, _file: File, onProgress: (share: number) => void) => {
      onProgress(0.5);
      return Promise.resolve<Attachment>({
        id: 8,
        card_id: 1,
        filename: 'план.pdf',
        content_type: 'application/pdf',
        size: 3,
        thumbnail: 'none',
        uploader_id: 1,
        created_at: '',
        url: '/f',
        thumbnail_url: null,
      });
    });
    const { user } = open('/boards/5?card=1');
    const dialog = await screen.findByRole('dialog');
    await user.upload(
      await within(dialog).findByLabelText('Прикрепить'),
      new File(['pdf'], 'план.pdf', { type: 'application/pdf' }),
    );
    expect(await within(dialog).findByRole('link', { name: 'план.pdf' })).toBeInTheDocument();
    expect(within(dialog).getAllByTestId('attachment')).toHaveLength(1);
  });

  it('слишком большой файл не отправляется', async () => {
    server.use(http.get(`${API}/cards/:id`, () => HttpResponse.json(detail())));
    const { user } = open('/boards/5?card=1');
    const dialog = await screen.findByRole('dialog');
    const big = new File([new Uint8Array(5 * 1024 * 1024 + 1)], 'видео.png', { type: 'image/png' });
    await user.upload(await within(dialog).findByLabelText('Прикрепить'), big);
    expect(await screen.findByText('«видео.png» больше 5 МБ')).toBeInTheDocument();
  });

  it('ошибка сервера при загрузке — понятный текст', async () => {
    server.use(http.get(`${API}/cards/:id`, () => HttpResponse.json(detail())));
    upload.fn.mockRejectedValue(new ApiError(415, 'unsupported_file', 'Такой файл прикрепить нельзя'));
    const { user } = open('/boards/5?card=1');
    const dialog = await screen.findByRole('dialog');
    await user.upload(
      await within(dialog).findByLabelText('Прикрепить'),
      new File(['x'], 'logo.txt', { type: 'text/plain' }),
    );
    expect(await screen.findByText('«logo.txt»: Такой файл прикрепить нельзя')).toBeInTheDocument();
  });
});

describe('живые события', () => {
  it('выгрузка: готовность приходит по WebSocket, файл можно скачать', async () => {
    server.use(
      http.post(`${API}/boards/:id/exports`, () =>
        HttpResponse.json(
          { id: 3, board_id: 5, status: 'pending', filename: null, created_at: '', finished_at: null },
          { status: 202 },
        ),
      ),
    );
    socketThen((client) =>
      setTimeout(() => {
        client.send(
          JSON.stringify({
            type: 'export.updated',
            id: 50,
            board_id: 5,
            actor_id: null,
            client_id: null,
            data: {
              id: 3,
              board_id: 5,
              status: 'ready',
              filename: 'Запуск.csv',
              created_at: '',
              finished_at: '',
            },
          }),
        );
      }, 150),
    );
    const { user } = open();
    await screen.findByText('Изменения видны всем сразу');
    await user.click(screen.getByRole('button', { name: /CSV/ }));
    expect(await screen.findByText('Готовим выгрузку — сообщим, когда будет готово')).toBeInTheDocument();
    expect(await screen.findByText('Выгрузка доски готова')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Скачать' })).toBeInTheDocument();
  });

  it('участника удалили с доски — уводим на список досок', async () => {
    socketThen((client) => client.close(4403));
    open();
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(/^\/$/));
    expect(await screen.findByText('Вас удалили с доски «Запуск»')).toBeInTheDocument();
  });

  it('лента действий пополняется вживую', async () => {
    server.use(
      http.get(`${API}/boards/:id/activity`, () =>
        HttpResponse.json([
          {
            id: 1,
            kind: 'card.created',
            message: 'Новая карточка «Купить домен»',
            actor: bauyrzhan,
            created_at: new Date().toISOString(),
          },
        ]),
      ),
    );
    socketThen((client) =>
      setTimeout(() => {
        client.send(
          JSON.stringify({
            type: 'card.deleted',
            id: 60,
            board_id: 5,
            actor_id: 2,
            client_id: null,
            data: {
              id: 2,
              column_id: 10,
              activity: {
                id: 2,
                kind: 'card.deleted',
                message: 'Карточка «Купить домен» удалена',
                actor: bauyrzhan,
                created_at: new Date().toISOString(),
              },
            },
          }),
        );
      }, 200),
    );
    const { user } = open();
    await screen.findByText('Изменения видны всем сразу');
    await user.click(screen.getByRole('button', { name: /Лента/ }));
    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText(/Новая карточка «Купить домен»/)).toBeInTheDocument();
    expect(await within(dialog).findByText(/Карточка «Купить домен» удалена/)).toBeInTheDocument();
    expect(within(lane('Нужно сделать')).queryByText('Купить домен')).not.toBeInTheDocument();
  });
});
