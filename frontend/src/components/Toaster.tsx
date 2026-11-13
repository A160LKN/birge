import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react';
import styles from './Toaster.module.css';

interface Toast {
  id: number;
  text: string;
  tone: 'info' | 'error' | 'success';
  action?: { label: string; onClick: () => void };
}
type ShowToast = (toast: Omit<Toast, 'id' | 'tone'> & { tone?: Toast['tone'] }) => void;

const ToastContext = createContext<ShowToast | null>(null);
const LIFETIME = 5000;

/** Короткие уведомления. Читаются экранными дикторами через aria-live. */
export function Toaster({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => setToasts((all) => all.filter((t) => t.id !== id)), []);
  const show = useCallback<ShowToast>(
    (toast) => {
      const id = nextId.current++;
      setToasts((all) => [...all.slice(-2), { tone: 'info', ...toast, id }]);
      setTimeout(() => dismiss(id), LIFETIME);
    },
    [dismiss],
  );
  const value = useMemo(() => show, [show]);

  return (
    <ToastContext value={value}>
      {children}
      <div className={styles.stack} aria-live="polite" role="status">
        {toasts.map((toast) => (
          <div key={toast.id} className={`${styles.toast} ${styles[toast.tone]}`}>
            <span>{toast.text}</span>
            {toast.action && (
              <button
                type="button"
                className={styles.action}
                onClick={() => {
                  toast.action?.onClick();
                  dismiss(toast.id);
                }}
              >
                {toast.action.label}
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastContext>
  );
}

export function useToast(): ShowToast {
  const show = useContext(ToastContext);
  if (!show) throw new Error('useToast вне Toaster');
  return show;
}
