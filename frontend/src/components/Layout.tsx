import { Link, Outlet } from 'react-router';
import { useAuth } from '@/auth/AuthProvider';
import { useTheme } from '@/lib/theme';
import { Avatar } from './Avatar';
import { Icon } from './Icon';
import styles from './Layout.module.css';

export function Layout() {
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  return (
    <div className={styles.shell}>
      <a href="#main" className={styles.skip}>
        К содержимому
      </a>
      <header className={styles.bar}>
        <Link to="/" className={styles.brand}>
          <svg width="26" height="18" viewBox="0 0 26 18" aria-hidden="true">
            <circle cx="9" cy="9" r="8" fill="#e4572e" />
            <circle cx="17" cy="9" r="8" fill="#2e86ab" fillOpacity="0.9" />
          </svg>
          Бірге
        </Link>
        <div className={styles.right}>
          <button
            type="button"
            className={styles.iconButton}
            onClick={toggle}
            aria-label={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
          >
            <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
          </button>
          {user && (
            <>
              <span className={styles.me}>
                <Avatar user={user} size="sm" />
                <span className={styles.name}>{user.name}</span>
              </span>
              <button type="button" className={styles.iconButton} onClick={logout} aria-label="Выйти">
                <Icon name="logout" />
              </button>
            </>
          )}
        </div>
      </header>
      <main id="main" className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}
