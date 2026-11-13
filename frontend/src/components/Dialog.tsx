import { useEffect, useRef, type ReactNode } from 'react';
import { Icon } from './Icon';
import styles from './Dialog.module.css';

interface Props {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
  /** Заголовок можно спрятать визуально (например, когда его роль играет поле ввода) */
  hideTitle?: boolean;
}

/** Модальное окно на нативном <dialog>: фокус, Esc и недоступность фона браузер делает сам. */
export function Dialog({ title, onClose, children, wide, hideTitle }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const close = useRef(onClose);
  close.current = onClose;

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    const onCancel = (event: Event) => {
      event.preventDefault();
      close.current();
    };
    dialog.addEventListener('cancel', onCancel);
    return () => dialog.removeEventListener('cancel', onCancel);
  }, []);

  return (
    <dialog
      ref={ref}
      className={`${styles.dialog} ${wide ? styles.wide : ''}`}
      aria-label={title}
      onClick={(event) => {
        if (event.target === ref.current) onClose(); // клик по затемнению
      }}
    >
      <div className={styles.inner}>
        <header className={styles.header}>
          <h2 className={hideTitle ? 'visually-hidden' : styles.title}>{title}</h2>
          <button type="button" className={styles.close} onClick={onClose} aria-label="Закрыть">
            <Icon name="close" />
          </button>
        </header>
        {children}
      </div>
    </dialog>
  );
}
