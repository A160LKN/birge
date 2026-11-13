import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import type { CSSProperties } from 'react';
import { fileUrl, type Card, type Member } from '@/api/client';
import { Avatar } from '@/components/Avatar';
import { Icon } from '@/components/Icon';
import { dueInfo } from '@/lib/dates';
import { personColor } from '@/lib/people';
import styles from './Board.module.css';

interface Props {
  card: Card;
  assignee: Member['user'] | undefined;
  /** Кто только что изменил карточку (другой человек) — подсветка его цветом */
  flashBy: Member['user'] | undefined;
  onOpen: (id: number) => void;
  overlay?: boolean;
}

export function CardFace({ card, assignee, flashBy, overlay }: Omit<Props, 'onOpen'>) {
  const due = card.due_date ? dueInfo(card.due_date) : null;
  return (
    <div
      className={`${styles.card} ${overlay ? styles.lifted : ''} ${flashBy ? styles.flash : ''}`}
      style={flashBy ? ({ '--person': personColor(flashBy.id) } as CSSProperties) : undefined}
    >
      {flashBy && (
        <span className={styles.flag} aria-hidden="true">
          {flashBy.name}
        </span>
      )}
      {card.cover_url && <img className={styles.cover} src={fileUrl(card.cover_url)} alt="" loading="lazy" />}
      <p className={styles.cardTitle}>{card.title}</p>
      {(due || card.comments > 0 || card.attachments > 0 || assignee) && (
        <div className={styles.meta}>
          {due && (
            <span className={`${styles.due} ${styles[due.tone]}`}>
              <Icon name="calendar" size={13} />
              {due.label}
            </span>
          )}
          {card.comments > 0 && (
            <span className={styles.count} title="Комментарии">
              <Icon name="comment" size={13} />
              {card.comments}
            </span>
          )}
          {card.attachments > 0 && (
            <span className={styles.count} title="Файлы">
              <Icon name="clip" size={13} />
              {card.attachments}
            </span>
          )}
          {assignee && (
            <span className={styles.assignee}>
              <Avatar user={assignee} size="sm" />
            </span>
          )}
        </div>
      )}
    </div>
  );
}

/** Карточка в колонке: перетаскивается мышью, пальцем и с клавиатуры (пробел — взять, стрелки, пробел — положить). */
export function CardTile({ card, assignee, flashBy, onOpen }: Props) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: card.id,
    data: { type: 'card', columnId: card.column_id },
  });
  const style: CSSProperties = { transform: CSS.Translate.toString(transform), transition };
  return (
    <li
      ref={setNodeRef}
      style={style}
      className={isDragging ? styles.placeholder : undefined}
      data-testid="card"
    >
      <button
        type="button"
        className={styles.cardButton}
        onClick={() => onOpen(card.id)}
        aria-label={`${card.title}${assignee ? `, исполнитель ${assignee.name}` : ''}`}
        {...attributes}
        {...listeners}
      >
        <CardFace card={card} assignee={assignee} flashBy={flashBy} />
      </button>
    </li>
  );
}
