import { useQueryClient } from '@tanstack/react-query';
import { useState, type SyntheticEvent } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import { api, call, type Board } from '@/api/client';
import { ApiError, errorMessage } from '@/api/errors';
import { keys, useActivity, useBoard } from '@/api/queries';
import { useAuth } from '@/auth/AuthProvider';
import { BoardView } from '@/board/BoardView';
import { CardDialog } from '@/board/CardDialog';
import { Avatar } from '@/components/Avatar';
import { Button, ButtonLink } from '@/components/Button';
import { Dialog } from '@/components/Dialog';
import { Field } from '@/components/Field';
import { Icon } from '@/components/Icon';
import { EmptyState, ErrorState, Spinner } from '@/components/States';
import { useToast } from '@/components/Toaster';
import { timeAgo } from '@/lib/dates';
import { useBoardSocket, watchExport, type Live } from '@/realtime/useBoardSocket';
import styles from './BoardPage.module.css';
import { formText } from '@/lib/form';

export function BoardPage() {
  const boardId = Number(useParams().boardId);
  const board = useBoard(boardId);
  const live = useBoardSocket(board.data);
  const [params, setParams] = useSearchParams();
  const openCard = params.get('card') ? Number(params.get('card')) : null;

  if (board.isPending) return <Spinner label="Загружаем доску" />;
  if (board.isError) {
    if (board.error instanceof ApiError && board.error.status === 404)
      return (
        <EmptyState
          title="Доска не найдена"
          text="Её удалили или вас не добавили в участники."
          action={<ButtonLink to="/">К моим доскам</ButtonLink>}
        />
      );
    return <ErrorState error={board.error} onRetry={() => void board.refetch()} />;
  }

  const setCard = (id: number | null) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (id === null) next.delete('card');
        else next.set('card', String(id));
        return next;
      },
      { replace: id === null },
    );

  return (
    <div className={styles.page}>
      <BoardHeader board={board.data} live={live} />
      <BoardView board={board.data} flashes={live.flashes} onOpen={setCard} />
      {openCard !== null && <CardDialog board={board.data} cardId={openCard} onClose={() => setCard(null)} />}
    </div>
  );
}

const STATUS_TEXT = {
  online: 'Изменения видны всем сразу',
  connecting: 'Подключаемся…',
  reconnecting: 'Связь прервалась — переподключаемся',
  offline: 'Нет интернета — изменения других не приходят',
} as const;

function BoardHeader({ board, live }: { board: Board; live: Live }) {
  const { user } = useAuth();
  const toast = useToast();
  const client = useQueryClient();
  const [panel, setPanel] = useState<'members' | 'activity' | null>(null);
  const [exporting, setExporting] = useState(false);
  const online = new Set(live.presence);
  const isOwner = board.role === 'owner';

  const rename = async (title: string) => {
    if (!title || title === board.title) return;
    try {
      await call(
        api.PATCH('/boards/{board_id}', { params: { path: { board_id: board.id } }, body: { title } }),
      );
      client.setQueryData<Board>(keys.board(board.id), (b) => b && { ...b, title });
    } catch (error) {
      toast({ text: errorMessage(error), tone: 'error' });
    }
  };

  const exportCsv = async () => {
    setExporting(true);
    try {
      const job = await call(
        api.POST('/boards/{board_id}/exports', { params: { path: { board_id: board.id } } }),
      );
      toast({ text: 'Готовим выгрузку — сообщим, когда будет готово' });
      watchExport(job.id, (event) => {
        setExporting(false);
        if (event.data.status === 'failed') {
          toast({ text: 'Не удалось подготовить выгрузку. Попробуйте ещё раз', tone: 'error' });
          return;
        }
        toast({
          text: 'Выгрузка доски готова',
          tone: 'success',
          action: {
            label: 'Скачать',
            onClick: () => void download(job.id, event.data.filename ?? 'board.csv'),
          },
        });
      });
    } catch (error) {
      setExporting(false);
      toast({ text: errorMessage(error), tone: 'error' });
    }
  };

  const download = async (id: number, filename: string) => {
    try {
      const { data, response } = await api.GET('/exports/{export_id}/download', {
        params: { path: { export_id: id } },
        parseAs: 'blob',
      });
      if (!response.ok || !data) throw new Error();
      const link = document.createElement('a');
      link.href = URL.createObjectURL(data);
      link.download = filename;
      document.body.append(link);
      link.click();
      link.remove();
      // Ссылку освобождаем не сразу: браузер должен успеть начать скачивание с правильным именем
      setTimeout(() => URL.revokeObjectURL(link.href), 10_000);
    } catch {
      toast({ text: 'Не удалось скачать файл', tone: 'error' });
    }
  };

  return (
    <header className={styles.header}>
      <div className={styles.titleRow}>
        <Link to="/" className={styles.back} aria-label="Все доски">
          <Icon name="back" />
        </Link>
        {isOwner ? (
          <input
            className={styles.title}
            defaultValue={board.title}
            key={board.title}
            aria-label="Название доски"
            maxLength={80}
            onBlur={(e) => void rename(e.currentTarget.value.trim())}
            onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
          />
        ) : (
          <h1 className={styles.titleText}>{board.title}</h1>
        )}
        <p className={`${styles.status} ${styles[live.status]}`} role="status" data-testid="connection">
          <span className={styles.dot} aria-hidden="true" />
          {STATUS_TEXT[live.status]}
        </p>
      </div>
      <div className={styles.actions}>
        <button
          type="button"
          className={styles.people}
          onClick={() => setPanel('members')}
          aria-label={`Участники: ${board.members.length}, сейчас на доске: ${live.presence.length}`}
        >
          {board.members.slice(0, 5).map((m) => (
            <Avatar key={m.user.id} user={m.user} online={online.has(m.user.id) && m.user.id !== user?.id} />
          ))}
          {board.members.length > 5 && <span className={styles.more}>+{board.members.length - 5}</span>}
        </button>
        <Button variant="ghost" size="sm" onClick={() => setPanel('activity')}>
          <Icon name="activity" size={16} /> Лента
        </Button>
        <Button variant="ghost" size="sm" onClick={() => void exportCsv()} loading={exporting}>
          <Icon name="download" size={16} /> CSV
        </Button>
      </div>
      {panel === 'members' && <MembersDialog board={board} online={online} onClose={() => setPanel(null)} />}
      {panel === 'activity' && <ActivityDialog board={board} onClose={() => setPanel(null)} />}
    </header>
  );
}

function MembersDialog({
  board,
  online,
  onClose,
}: {
  board: Board;
  online: Set<number>;
  onClose: () => void;
}) {
  const { user } = useAuth();
  const client = useQueryClient();
  const toast = useToast();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const isOwner = board.role === 'owner';

  const invite = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const email = formText(form, 'email');
    if (!email) return;
    setBusy(true);
    setError(undefined);
    try {
      const member = await call(
        api.POST('/boards/{board_id}/members', { params: { path: { board_id: board.id } }, body: { email } }),
      );
      client.setQueryData<Board>(keys.board(board.id), (b) =>
        b && !b.members.some((m) => m.user.id === member.user.id)
          ? { ...b, members: [...b.members, member] }
          : b,
      );
      form.reset();
      toast({ text: `${member.user.name} теперь на доске`, tone: 'success' });
    } catch (e) {
      setError(e instanceof ApiError && e.fields.email ? 'Неверный формат email' : errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: number, name: string) => {
    const self = id === user?.id;
    if (
      !window.confirm(
        self ? 'Покинуть доску?' : `Убрать ${name} с доски? Его карточки останутся без исполнителя.`,
      )
    )
      return;
    try {
      await call(
        api.DELETE('/boards/{board_id}/members/{user_id}', {
          params: { path: { board_id: board.id, user_id: id } },
        }),
      );
      client.setQueryData<Board>(
        keys.board(board.id),
        (b) => b && { ...b, members: b.members.filter((m) => m.user.id !== id) },
      );
    } catch (e) {
      toast({ text: errorMessage(e), tone: 'error' });
    }
  };

  return (
    <Dialog title="Участники" onClose={onClose}>
      <ul className={styles.members}>
        {board.members.map((m) => (
          <li key={m.user.id}>
            <Avatar user={m.user} online={online.has(m.user.id)} />
            <div className={styles.memberInfo}>
              <strong>
                {m.user.name}
                {m.user.id === user?.id && ' (вы)'}
              </strong>
              <span>
                {m.role === 'owner' ? 'владелец' : 'участник'}
                {online.has(m.user.id) && ' · на доске'}
              </span>
            </div>
            {m.role !== 'owner' && (isOwner || m.user.id === user?.id) && (
              <Button variant="ghost" size="sm" onClick={() => void remove(m.user.id, m.user.name)}>
                {m.user.id === user?.id ? 'Покинуть' : 'Убрать'}
              </Button>
            )}
          </li>
        ))}
      </ul>
      {isOwner && (
        <form className={styles.invite} onSubmit={invite} noValidate>
          <Field
            label="Пригласить по email"
            name="email"
            type="email"
            placeholder="коллега@компания.kz"
            error={error}
            hint="Человек должен быть зарегистрирован в Бірге"
          />
          <Button type="submit" loading={busy}>
            Добавить
          </Button>
        </form>
      )}
    </Dialog>
  );
}

function ActivityDialog({ board, onClose }: { board: Board; onClose: () => void }) {
  const feed = useActivity(board.id, true);
  return (
    <Dialog title="Лента действий" onClose={onClose}>
      {feed.isPending && <Spinner />}
      {feed.isError && <ErrorState error={feed.error} onRetry={() => void feed.refetch()} />}
      {feed.isSuccess && feed.data.length === 0 && (
        <p className={styles.muted}>Здесь появится всё, что происходит на доске.</p>
      )}
      {feed.isSuccess && (
        <ol className={styles.feed}>
          {feed.data.map((a) => (
            <li key={a.id}>
              {a.actor ? <Avatar user={a.actor} size="sm" /> : <span className={styles.ghost} />}
              <div>
                <p>
                  <strong>{a.actor?.name ?? 'Бывший участник'}</strong> · {a.message}
                </p>
                <time dateTime={a.created_at}>{timeAgo(a.created_at)}</time>
              </div>
            </li>
          ))}
        </ol>
      )}
    </Dialog>
  );
}
