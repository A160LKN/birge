import { initials, personColor } from '@/lib/people';
import styles from './Avatar.module.css';

interface Props {
  user: { id: number; name: string };
  size?: 'sm' | 'md';
  online?: boolean;
}

/** Кружок с инициалами в цвете человека. Имя — в title и для экранных дикторов. */
export function Avatar({ user, size = 'md', online }: Props) {
  return (
    <span
      className={`${styles.avatar} ${styles[size]} ${online ? styles.online : ''}`}
      style={{ '--person': personColor(user.id) } as React.CSSProperties}
      title={user.name}
    >
      <span aria-hidden="true">{initials(user.name)}</span>
      <span className="visually-hidden">{user.name}</span>
    </span>
  );
}
