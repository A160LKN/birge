import { QueryClient } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { tokenStore } from '@/auth/token';
import { Providers } from '@/providers';

function Location() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

interface Options {
  route?: string;
  path?: string;
  loggedIn?: boolean;
}

/** Страница со всеми провайдерами, как в приложении. Свой QueryClient на тест — без утечек кеша. */
export function renderPage(ui: ReactElement, { route = '/', path = '*', loggedIn = false }: Options = {}) {
  tokenStore.set(loggedIn ? 'test-token' : null);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const result = render(
    <MemoryRouter initialEntries={[route]}>
      <Providers client={client}>
        <Routes>
          <Route path={path} element={ui} />
          <Route path="*" element={<p>другая страница</p>} />
        </Routes>
        <Location />
      </Providers>
    </MemoryRouter>,
  );
  return { ...result, client, user: userEvent.setup() };
}
