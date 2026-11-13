import { useState, type SyntheticEvent } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router';
import { ApiError, errorMessage } from '@/api/errors';
import { useAuth } from '@/auth/AuthProvider';
import { safeNext } from '@/auth/guards';
import { Button } from '@/components/Button';
import { Field } from '@/components/Field';
import { Notice } from '@/components/States';
import { formText } from '@/lib/form';
import styles from './AuthPage.module.css';

const DEMO = { email: 'aliya@birge.kz', second: 'bauyrzhan@birge.kz', password: 'birge-demo' };

export function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  const { user, login, register } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNext(params.get('next'));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | Error | null>(null);

  if (user) return <Navigate to={next} replace />;

  const submit = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const email = formText(form, 'email');
    const raw = new FormData(form).get('password');
    const password = typeof raw === 'string' ? raw : ''; // пароль не обрезаем: пробелы — тоже символы
    setBusy(true);
    setError(null);
    try {
      if (mode === 'register') await register(email, formText(form, 'name'), password);
      else await login(email, password);
      void navigate(next, { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e : new Error(errorMessage(e)));
      setBusy(false);
    }
  };

  const fields = error instanceof ApiError ? error.fields : {};
  const demo = async () => {
    setBusy(true);
    try {
      await login(DEMO.email, DEMO.password);
      void navigate(next, { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e : new Error(errorMessage(e)));
      setBusy(false);
    }
  };

  return (
    <div className={styles.page}>
      <section className={styles.intro}>
        <h1 className={styles.headline}>Доска, на которой команда видит одно и то же</h1>
        <p className={styles.lead}>
          Коллега перенёс карточку — у вас она переехала в ту же секунду, подсвеченная его цветом. Двое правят
          одно описание — никто не затрёт чужой текст молча.
        </p>
        <Beads />
      </section>

      <section className={styles.formCard}>
        <h2>{mode === 'login' ? 'Вход' : 'Регистрация'}</h2>
        {error && !Object.keys(fields).length && <Notice tone="error">{error.message}</Notice>}
        <form onSubmit={submit} className={styles.form} noValidate>
          {mode === 'register' && (
            <Field
              label="Как вас зовут"
              name="name"
              autoComplete="name"
              required
              maxLength={60}
              error={fields.name && 'Укажите имя'}
            />
          )}
          <Field
            label="Email"
            name="email"
            type="email"
            autoComplete="email"
            required
            error={fields.email && 'Неверный формат email'}
          />
          <Field
            label="Пароль"
            name="password"
            type="password"
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            required
            hint={mode === 'register' ? 'Не короче 8 символов' : undefined}
            error={fields.password && 'Не короче 8 символов'}
          />
          <Button type="submit" size="lg" loading={busy}>
            {mode === 'login' ? 'Войти' : 'Создать аккаунт'}
          </Button>
        </form>
        <p className={styles.switch}>
          {mode === 'login' ? (
            <>
              Нет аккаунта?{' '}
              <Link to={`/register${params.size ? `?${params.toString()}` : ''}`}>Зарегистрироваться</Link>
            </>
          ) : (
            <>
              Уже есть аккаунт? <Link to={`/login${params.size ? `?${params.toString()}` : ''}`}>Войти</Link>
            </>
          )}
        </p>
        {mode === 'login' && (
          <div className={styles.demo}>
            <p>
              Попробуйте вдвоём: откройте сайт в двух браузерах и войдите как <strong>{DEMO.email}</strong> и{' '}
              <strong>{DEMO.second}</strong>, пароль <code>{DEMO.password}</code>.
            </p>
            <Button variant="secondary" size="sm" onClick={() => void demo()} disabled={busy}>
              Войти как Алия
            </Button>
          </div>
        )}
      </section>
    </div>
  );
}

/** Бусины участников: каждый — своего цвета, вместе — одна нить. */
function Beads() {
  const colors = ['#e4572e', '#2e86ab', '#a23b72', '#d48a00', '#3b8b5a'];
  return (
    <svg className={styles.beads} viewBox="0 0 320 60" aria-hidden="true">
      <path
        d="M0 30 C 60 6, 100 54, 160 30 S 260 6, 320 30"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      {colors.map((color, i) => (
        <circle key={color} cx={32 + i * 64} cy={i % 2 ? 36 : 22} r="13" fill={color} />
      ))}
    </svg>
  );
}
