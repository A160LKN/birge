import { useState, type SyntheticEvent } from 'react';
import { Link, useNavigate } from 'react-router';
import { errorMessage } from '@/api/errors';
import { useBoards, useCreateBoard } from '@/api/queries';
import { Button } from '@/components/Button';
import { ErrorState, Spinner } from '@/components/States';
import { plural } from '@/lib/plural';
import styles from './BoardsPage.module.css';
import { formText } from '@/lib/form';

export function BoardsPage() {
  const boards = useBoards();
  const create = useCreateBoard();
  const navigate = useNavigate();
  const [error, setError] = useState<string>();

  const submit = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    const title = formText(event.currentTarget, 'title');
    if (!title) {
      setError('Назовите доску');
      return;
    }
    setError(undefined);
    try {
      const board = await create.mutateAsync(title);
      void navigate(`/boards/${board.id}`);
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <div className={styles.page}>
      <h1>Мои доски</h1>
      <form className={styles.create} onSubmit={submit} noValidate>
        <label htmlFor="board-title" className="visually-hidden">
          Название новой доски
        </label>
        <input
          id="board-title"
          name="title"
          placeholder="Новая доска, например «Запуск сайта»"
          maxLength={80}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? 'board-error' : undefined}
        />
        <Button type="submit" loading={create.isPending}>
          Создать доску
        </Button>
      </form>
      {error && (
        <p id="board-error" className={styles.error}>
          {error}
        </p>
      )}

      {boards.isPending && <Spinner />}
      {boards.isError && <ErrorState error={boards.error} onRetry={() => void boards.refetch()} />}
      {boards.isSuccess && boards.data.length === 0 && (
        <p className={styles.empty}>
          Досок пока нет. Создайте первую — в ней сразу будут колонки «Нужно сделать», «В работе» и «Готово».
        </p>
      )}
      {boards.isSuccess && boards.data.length > 0 && (
        <ul className={styles.grid}>
          {boards.data.map((b) => (
            <li key={b.id}>
              <Link to={`/boards/${b.id}`} className={styles.tile} data-testid="board-tile">
                <span className={styles.tileTitle}>{b.title}</span>
                <span className={styles.tileMeta}>
                  {b.cards} {plural(b.cards, ['карточка', 'карточки', 'карточек'])} · {b.members}{' '}
                  {plural(b.members, ['участник', 'участника', 'участников'])}
                </span>
                {b.role === 'owner' && <span className={styles.badge}>ваша</span>}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
