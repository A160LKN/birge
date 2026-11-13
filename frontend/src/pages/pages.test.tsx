import { screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { tokenStore } from '@/auth/token';
import { API, aliya, appError, server } from '@/test/server';
import { renderPage } from '@/test/render';
import { AuthPage } from './AuthPage';
import { BoardsPage } from './BoardsPage';

describe('вход', () => {
  it('успешный вход сохраняет токен и возвращает туда, откуда пришли', async () => {
    server.use(
      http.post(`${API}/auth/login`, () =>
        HttpResponse.json({ access_token: 'tok', token_type: 'bearer', user: aliya }),
      ),
    );
    const { user } = renderPage(<AuthPage mode="login" />, { route: '/login?next=%2Fboards%2F5' });
    await user.type(screen.getByLabelText('Email'), 'aliya@test.kz');
    await user.type(screen.getByLabelText('Пароль'), 'secret-pass');
    await user.click(screen.getByRole('button', { name: 'Войти' }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/boards/5'));
    expect(tokenStore.get()).toBe('tok');
  });

  it('ошибка входа показывается текстом сервера', async () => {
    server.use(
      http.post(`${API}/auth/login`, () => appError(401, 'invalid_credentials', 'Неверный email или пароль')),
    );
    const { user } = renderPage(<AuthPage mode="login" />, { route: '/login' });
    await user.type(screen.getByLabelText('Email'), 'a@test.kz');
    await user.type(screen.getByLabelText('Пароль'), 'wrong-pass');
    await user.click(screen.getByRole('button', { name: 'Войти' }));
    expect(await screen.findByText('Неверный email или пароль')).toBeInTheDocument();
  });

  it('редирект после входа — только внутри сайта', async () => {
    server.use(
      http.post(`${API}/auth/login`, () =>
        HttpResponse.json({ access_token: 'tok', token_type: 'bearer', user: aliya }),
      ),
    );
    const { user } = renderPage(<AuthPage mode="login" />, { route: '/login?next=%2F%2Fevil.example' });
    await user.click(screen.getByRole('button', { name: 'Войти как Алия' }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(/^\/$/));
  });

  it('регистрация: ошибки валидации — у полей', async () => {
    server.use(
      http.post(`${API}/auth/register`, () =>
        HttpResponse.json({ detail: [{ loc: ['body', 'password'], msg: 'too short' }] }, { status: 422 }),
      ),
    );
    const { user } = renderPage(<AuthPage mode="register" />, { route: '/register' });
    await user.type(screen.getByLabelText('Как вас зовут'), 'Айбол');
    await user.type(screen.getByLabelText('Email'), 'a@test.kz');
    await user.type(screen.getByLabelText('Пароль'), 'short');
    await user.click(screen.getByRole('button', { name: 'Создать аккаунт' }));
    expect(
      await screen.findByText('Не короче 8 символов', { selector: '[id$="-error"]' }),
    ).toBeInTheDocument();
  });
});

describe('мои доски', () => {
  it('пусто — подсказка', async () => {
    renderPage(<BoardsPage />, { loggedIn: true });
    expect(await screen.findByText(/Досок пока нет/)).toBeInTheDocument();
  });

  it('список с ролью и склонениями', async () => {
    server.use(
      http.get(`${API}/boards`, () =>
        HttpResponse.json([
          { id: 1, title: 'Релиз', role: 'owner', members: 2, cards: 5 },
          { id: 2, title: 'Маркетинг', role: 'member', members: 1, cards: 1 },
        ]),
      ),
    );
    renderPage(<BoardsPage />, { loggedIn: true });
    const tiles = await screen.findAllByTestId('board-tile');
    expect(within(tiles[0] as HTMLElement).getByText('5 карточек · 2 участника')).toBeInTheDocument();
    expect(within(tiles[0] as HTMLElement).getByText('ваша')).toBeInTheDocument();
    expect(within(tiles[1] as HTMLElement).getByText('1 карточка · 1 участник')).toBeInTheDocument();
  });

  it('новая доска открывается сразу после создания', async () => {
    server.use(
      http.post(`${API}/boards`, () => HttpResponse.json({ id: 77, title: 'Новая' }, { status: 201 })),
    );
    const { user } = renderPage(<BoardsPage />, { loggedIn: true });
    await user.type(await screen.findByLabelText('Название новой доски'), 'Новая');
    await user.click(screen.getByRole('button', { name: 'Создать доску' }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/boards/77'));
  });

  it('пустое название — подсказка, запрос не уходит', async () => {
    const { user } = renderPage(<BoardsPage />, { loggedIn: true });
    await user.click(await screen.findByRole('button', { name: 'Создать доску' }));
    expect(screen.getByText('Назовите доску')).toBeInTheDocument();
  });
});
