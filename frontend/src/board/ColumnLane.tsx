import { useDroppable } from '@dnd-kit/core';
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { useState, type SyntheticEvent } from 'react';
import { ApiError, errorMessage } from '@/api/errors';
import type { Card, Column, Member } from '@/api/client';
import { Icon } from '@/components/Icon';
import { useToast } from '@/components/Toaster';
import { CardTile } from './CardTile';
import styles from './Board.module.css';
import { formText } from '@/lib/form';

interface Props {
  column: Column;
  cards: Card[];
  members: Map<number, Member['user']>;
  flashes: ReadonlyMap<number, number>;
  onOpen: (id: number) => void;
  onAddCard: (columnId: number, title: string) => Promise<unknown>;
  onRename: (column: Column, title: string) => Promise<unknown>;
  onDelete: (column: Column) => Promise<unknown>;
  onMove: (column: Column, direction: -1 | 1) => Promise<unknown>;
  isFirst: boolean;
  isLast: boolean;
}

export function ColumnLane(props: Props) {
  const { column, cards, members, flashes, onOpen } = props;
  const { setNodeRef, isOver } = useDroppable({
    id: `column-${column.id}`,
    data: { type: 'column', columnId: column.id },
  });
  return (
    <section className={styles.lane} aria-labelledby={`column-${column.id}-title`} data-testid="column">
      <ColumnHeader {...props} />
      <SortableContext items={cards.map((c) => c.id)} strategy={verticalListSortingStrategy}>
        <ol ref={setNodeRef} className={`${styles.cards} ${isOver ? styles.over : ''}`}>
          {cards.map((card) => (
            <CardTile
              key={card.id}
              card={card}
              assignee={card.assignee_id ? members.get(card.assignee_id) : undefined}
              flashBy={flashes.has(card.id) ? members.get(flashes.get(card.id) ?? 0) : undefined}
              onOpen={onOpen}
            />
          ))}
        </ol>
      </SortableContext>
      <AddCard onAdd={(title) => props.onAddCard(column.id, title)} />
    </section>
  );
}

function ColumnHeader({ column, cards, onRename, onDelete, onMove, isFirst, isLast }: Props) {
  const [editing, setEditing] = useState(false);
  const [menu, setMenu] = useState(false);
  const toast = useToast();

  const rename = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    const title = formText(event.currentTarget, 'title');
    setEditing(false);
    if (title && title !== column.title)
      await onRename(column, title).catch((e: unknown) => toast({ text: errorMessage(e), tone: 'error' }));
  };

  const remove = async () => {
    setMenu(false);
    const note = cards.length ? ` Вместе с ней удалятся карточки: ${cards.length}.` : '';
    if (!window.confirm(`Удалить колонку «${column.title}»?${note}`)) return;
    await onDelete(column).catch((e: unknown) =>
      toast({ text: e instanceof ApiError ? e.message : errorMessage(e), tone: 'error' }),
    );
  };

  return (
    <header className={styles.laneHeader}>
      {editing ? (
        <form onSubmit={rename} className={styles.laneForm}>
          <input
            name="title"
            defaultValue={column.title}
            maxLength={40}
            aria-label="Название колонки"
            autoFocus
            onBlur={(e) => e.currentTarget.form?.requestSubmit()}
            onKeyDown={(e) => e.key === 'Escape' && setEditing(false)}
          />
        </form>
      ) : (
        <h2
          id={`column-${column.id}-title`}
          className={styles.laneTitle}
          onDoubleClick={() => setEditing(true)}
        >
          {column.title}
          <span className={styles.laneCount}>{cards.length}</span>
        </h2>
      )}
      <div className={styles.menuWrap}>
        <button
          type="button"
          className={styles.iconButton}
          aria-label={`Действия с колонкой «${column.title}»`}
          aria-expanded={menu}
          onClick={() => setMenu((open) => !open)}
        >
          <Icon name="more" />
        </button>
        {menu && (
          <ul className={styles.menu} onMouseLeave={() => setMenu(false)}>
            <li>
              <button
                type="button"
                onClick={() => {
                  setMenu(false);
                  setEditing(true);
                }}
              >
                Переименовать
              </button>
            </li>
            {!isFirst && (
              <li>
                <button
                  type="button"
                  onClick={() => {
                    setMenu(false);
                    void onMove(column, -1);
                  }}
                >
                  Сдвинуть левее
                </button>
              </li>
            )}
            {!isLast && (
              <li>
                <button
                  type="button"
                  onClick={() => {
                    setMenu(false);
                    void onMove(column, 1);
                  }}
                >
                  Сдвинуть правее
                </button>
              </li>
            )}
            <li>
              <button type="button" className={styles.danger} onClick={() => void remove()}>
                Удалить колонку
              </button>
            </li>
          </ul>
        )}
      </div>
    </header>
  );
}

function AddCard({ onAdd }: { onAdd: (title: string) => Promise<unknown> }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const submit = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const title = formText(form, 'title');
    if (!title) return;
    setBusy(true);
    try {
      await onAdd(title);
      form.reset(); // форма остаётся открытой — можно сразу добавить следующую
    } catch (error) {
      toast({ text: errorMessage(error), tone: 'error' });
    } finally {
      setBusy(false);
    }
  };

  if (!open)
    return (
      <button type="button" className={styles.addCard} onClick={() => setOpen(true)}>
        <Icon name="plus" size={16} /> Добавить карточку
      </button>
    );
  return (
    <form className={styles.addForm} onSubmit={submit}>
      <textarea
        name="title"
        aria-label="Название новой карточки"
        placeholder="Что нужно сделать?"
        maxLength={200}
        rows={2}
        autoFocus
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            e.currentTarget.form?.requestSubmit();
          }
          if (e.key === 'Escape') setOpen(false);
        }}
      />
      <div className={styles.addActions}>
        <button type="submit" className={styles.addSubmit} disabled={busy}>
          Добавить
        </button>
        <button
          type="button"
          className={styles.iconButton}
          onClick={() => setOpen(false)}
          aria-label="Отмена"
        >
          <Icon name="close" />
        </button>
      </div>
    </form>
  );
}
