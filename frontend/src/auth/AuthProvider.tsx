import { useQuery, useQueryClient } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api, call, type User } from '@/api/client';
import { keys } from '@/api/queries';
import { tokenStore } from './token';

interface AuthState {
  user: User | null;
  /** true, пока проверяем сохранённый токен — чтобы не мигать формой входа у вошедшего */
  checking: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (email: string, name: string, password: string) => Promise<User>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [token, setToken] = useState(tokenStore.get);

  useEffect(
    () =>
      tokenStore.subscribe((next) => {
        setToken(next);
        if (next === null) queryClient.clear(); // вышли — чужие доски не остаются в кеше
      }),
    [queryClient],
  );

  const me = useQuery({
    queryKey: [...keys.me, token],
    queryFn: () => call(api.GET('/auth/me')),
    enabled: token !== null,
    staleTime: Infinity,
    retry: false,
  });

  const signIn = useCallback(
    (access_token: string, user: User) => {
      tokenStore.set(access_token);
      queryClient.setQueryData([...keys.me, access_token], user);
      return user;
    },
    [queryClient],
  );

  const login = useCallback(
    async (email: string, password: string) => {
      const result = await call(api.POST('/auth/login', { body: { email, password } }));
      return signIn(result.access_token, result.user);
    },
    [signIn],
  );

  const register = useCallback(
    async (email: string, name: string, password: string) => {
      const result = await call(api.POST('/auth/register', { body: { email, name, password } }));
      return signIn(result.access_token, result.user);
    },
    [signIn],
  );

  const logout = useCallback(() => tokenStore.set(null), []);

  const value = useMemo<AuthState>(
    () => ({
      user: token ? (me.data ?? null) : null,
      checking: token !== null && me.isPending,
      login,
      register,
      logout,
    }),
    [token, me.data, me.isPending, login, register, logout],
  );
  return <AuthContext value={value}>{children}</AuthContext>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth вне AuthProvider');
  return context;
}
