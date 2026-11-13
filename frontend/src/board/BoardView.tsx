import {
  closestCorners,
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type Announcements,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from '@dnd-kit/core';
import { arrayMove, sortableKeyboardCoordinates } from '@dnd-kit/sortable';
import { useQueryClient } from '@tanstack/react-query';
import { useMemo, useState, type SyntheticEvent } from 'react';
import { api, call, type Board, type Column } from '@/api/client';
import { errorMessage } from '@/api/errors';
import { keys, putCard, useCreateCard, useCreateColumn } from '@/api/queries';
import { Icon } from '@/components/Icon';
import { useToast } from '@/components/Toaster';
import { CardFace } from './CardTile';
import { ColumnLane } from './ColumnLane';
import { columnsInOrder, findColumn, lanesOf, moveInLanes, planMove, type Lanes } from './order';
import styles from './Board.module.css';
import { formText } from '@/lib/form';

interface Props {
  board: Board;
  flashes: ReadonlyMap<number, number>;
  onOpen: (id: number) => void;
}

const columnOf = (id: string | number | undefined, lanes: Lanes): number | undefined => {
  if (typeof id === 'string' && id.startsWith('column-')) return Number(id.slice(7));
  return typeof id === 'number' ? findColumn(lanes, id) : undefined;
};

export function BoardView({ board, flashes, onOpen }: Props) {
  const client = useQueryClient();
  const toast = useToast();
  const createCard = useCreateCard(board.id);
  const createColumn = useCreateColumn(board.id);
  const [drag, setDrag] = useState<{ id: number; lanes: Lanes } | null>(null);

  const columns = useMemo(() => columnsInOrder(board), [board]);
  const lanes = useMemo(() => drag?.lanes ?? lanesOf(board), [board, drag]);
  const cards = useMemo(() => new Map(board.cards.map((c) => [c.id, c])), [board.cards]);
  const members = useMemo(() => new Map(board.members.map((m) => [m.user.id, m.user])), [board.members]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }), // клик по карточке — не перетаскивание
    useSensor(TouchSensor, { activationConstraint: { delay: 180, tolerance: 6 } }), // свайп листает доску
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const titleOf = (id: string | number) => cards.get(Number(id))?.title ?? 'карточка';
  const columnTitle = (id: string | number | undefined) =>
    board.columns.find((c) => c.id === columnOf(id, lanes))?.title ?? '';
  const announcements: Announcements = {
    onDragStart: ({ active }) =>
      `Карточка «${titleOf(active.id)}» взята. Стрелки — переместить, пробел — положить.`,
    onDragOver: ({ active, over }) =>
      over ? `«${titleOf(active.id)}» над колонкой «${columnTitle(over.id)}»` : undefined,
    onDragEnd: ({ active, over }) =>
      over ? `«${titleOf(active.id)}» положена в колонку «${columnTitle(over.id)}»` : 'Перенос отменён',
    onDragCancel: ({ active }) => `Перенос «${titleOf(active.id)}» отменён`,
  };

  const onDragStart = ({ active }: DragStartEvent) =>
    setDrag({ id: Number(active.id), lanes: lanesOf(board) });

  const onDragOver = ({ active, over }: DragOverEvent) => {
    if (!drag || !over) return;
    const from = findColumn(drag.lanes, drag.id);
    const to = columnOf(over.id, drag.lanes);
    if (to === undefined || from === to) return;
    // Карточка перешла в другую колонку — показываем её там сразу, ещё до того как отпустили
    const target = drag.lanes[to] ?? [];
    const overIndex = typeof over.id === 'number' ? target.indexOf(over.id) : target.length;
    const dragged = active.rect.current.translated;
    const below = dragged !== null && dragged.top > over.rect.top;
    const index = overIndex < 0 ? target.length : overIndex + (below ? 1 : 0);
    setDrag({ ...drag, lanes: moveInLanes(drag.lanes, drag.id, to, index) });
  };

  const onDragEnd = ({ over }: DragEndEvent) => {
    if (!drag) return;
    const column = findColumn(drag.lanes, drag.id);
    let finalLanes = drag.lanes;
    if (over && typeof over.id === 'number' && over.id !== drag.id && column !== undefined) {
      // Внутри колонки — как arrayMove: вниз встаёт после карточки, над которой отпустили, вверх — перед ней
      const ids = drag.lanes[column] ?? [];
      if (ids.includes(over.id)) {
        finalLanes = { ...drag.lanes, [column]: arrayMove(ids, ids.indexOf(drag.id), ids.indexOf(over.id)) };
      }
    }
    setDrag(null);
    if (!over) return;
    const plan = planMove(board, finalLanes, drag.id);
    if (plan) void move(drag.id, plan);
  };

  const move = async (cardId: number, plan: NonNullable<ReturnType<typeof planMove>>) => {
    const key = keys.board(board.id);
    const snapshot = client.getQueryData<Board>(key);
    // Мгновенно у себя — без ожидания сервера. Не получилось — возвращаем как было
    client.setQueryData<Board>(key, (current) => current && putCard(current, plan.optimistic));
    try {
      const saved = await call(
        api.POST('/cards/{card_id}/move', { params: { path: { card_id: cardId } }, body: plan.request }),
      );
      client.setQueryData<Board>(key, (current) => current && putCard(current, saved));
    } catch (error) {
      if (snapshot) client.setQueryData(key, snapshot);
      toast({ text: `Не удалось перенести карточку: ${errorMessage(error)}`, tone: 'error' });
      void client.invalidateQueries({ queryKey: key });
    }
  };

  const updateColumn = (column: Column) =>
    client.setQueryData<Board>(
      keys.board(board.id),
      (current) =>
        current && { ...current, columns: current.columns.map((c) => (c.id === column.id ? column : c)) },
    );

  const renameColumn = async (column: Column, title: string) =>
    updateColumn(
      await call(
        api.PATCH('/columns/{column_id}', { params: { path: { column_id: column.id } }, body: { title } }),
      ),
    );

  const moveColumn = async (column: Column, direction: -1 | 1) => {
    const index = columns.findIndex((c) => c.id === column.id);
    // Левее — после колонки через одну слева; правее — после соседа справа
    const after = direction === -1 ? (columns[index - 2]?.id ?? null) : (columns[index + 1]?.id ?? null);
    updateColumn(
      await call(
        api.POST('/columns/{column_id}/move', {
          params: { path: { column_id: column.id } },
          body: { after_id: after },
        }),
      ),
    );
  };

  const deleteColumn = async (column: Column) => {
    await call(api.DELETE('/columns/{column_id}', { params: { path: { column_id: column.id } } }));
    client.setQueryData<Board>(
      keys.board(board.id),
      (current) =>
        current && {
          ...current,
          columns: current.columns.filter((c) => c.id !== column.id),
          cards: current.cards.filter((c) => c.column_id !== column.id),
        },
    );
  };

  const addColumn = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const title = formText(form, 'title');
    if (!title) return;
    try {
      await createColumn.mutateAsync(title);
      form.reset();
    } catch (error) {
      toast({ text: errorMessage(error), tone: 'error' });
    }
  };

  const dragged = drag ? cards.get(drag.id) : undefined;

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDragEnd={onDragEnd}
      onDragCancel={() => setDrag(null)}
      accessibility={{
        announcements,
        screenReaderInstructions: {
          draggable:
            'Чтобы перенести карточку, нажмите пробел, выберите место стрелками и нажмите пробел ещё раз.',
        },
      }}
    >
      <div className={styles.lanes}>
        {columns.map((column, index) => (
          <ColumnLane
            key={column.id}
            column={column}
            cards={(lanes[column.id] ?? []).flatMap((id) => cards.get(id) ?? [])}
            members={members}
            flashes={flashes}
            onOpen={onOpen}
            onAddCard={(columnId, title) => createCard.mutateAsync({ column_id: columnId, title })}
            onRename={renameColumn}
            onDelete={deleteColumn}
            onMove={moveColumn}
            isFirst={index === 0}
            isLast={index === columns.length - 1}
          />
        ))}
        <form className={styles.newLane} onSubmit={addColumn}>
          <label htmlFor="new-column" className="visually-hidden">
            Новая колонка
          </label>
          <input id="new-column" name="title" placeholder="Новая колонка" maxLength={40} />
          <button type="submit" className={styles.iconButton} aria-label="Добавить колонку">
            <Icon name="plus" />
          </button>
        </form>
      </div>
      <DragOverlay dropAnimation={{ duration: 160, easing: 'ease-out' }}>
        {dragged && (
          <CardFace
            card={dragged}
            assignee={dragged.assignee_id ? members.get(dragged.assignee_id) : undefined}
            flashBy={undefined}
            overlay
          />
        )}
      </DragOverlay>
    </DndContext>
  );
}
