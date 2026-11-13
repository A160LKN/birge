import { Route, Routes } from 'react-router';
import { RequireAuth } from '@/auth/guards';
import { Layout } from '@/components/Layout';
import { AuthPage } from '@/pages/AuthPage';
import { BoardPage } from '@/pages/BoardPage';
import { BoardsPage } from '@/pages/BoardsPage';
import { NotFoundPage } from '@/pages/NotFoundPage';

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/login" element={<AuthPage mode="login" />} />
        <Route path="/register" element={<AuthPage mode="register" />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <BoardsPage />
            </RequireAuth>
          }
        />
        <Route
          path="/boards/:boardId"
          element={
            <RequireAuth>
              <BoardPage />
            </RequireAuth>
          }
        />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
