import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState, type SyntheticEvent } from 'react';
import {
  api,
  call,
  fileUrl,
  type Attachment,
  type Board,
  type CardDetail,
  type CardPatch,
} from '@/api/client';
import { ApiError, errorMessage } from '@/api/errors';
import { keys, useCard, useUpdateCard } from '@/api/queries';
import { Avatar } from '@/components/Avatar';
import { Button } from '@/components/Button';
import { Dialog } from '@/components/Dialog';
import { Icon } from '@/components/Icon';
import { ErrorState, Notice, Spinner } from '@/components/States';
import { useToast } from '@/components/Toaster';
import { uploadFile } from '@/api/upload';
import { fileSize, timeAgo } from '@/lib/dates';
import styles from './CardDialog.module.css';
import { formText } from '@/lib/form';

interface Props {
  board: Board;
  cardId: number;
  onClose: () => void;
}

export function CardDialog({ board, cardId, onClose }: Props) {
  const card = useCard(cardId);
  const stillOnBoard = board.cards.some((c) => c.id === cardId);
  return (
    <Dialog title={card.data?.title ?? 'Карточка'} onClose={onClose} wide hideTitle={card.isSuccess}>
      {card.isPending && <Spinner />}
      {card.isError &&
        (card.error instanceof ApiError && card.error.status === 404 ? (
          <Notice tone="warning">Карточку удалили или у вас больше нет к ней доступа.</Notice>
        ) : (
          <ErrorState error={card.error} onRetry={() => void card.refetch()} />
        ))}
      {card.isSuccess &&
        (stillOnBoard ? (
          <CardEditor board={board} card={card.data} onClose={onClose} />
        ) : (
          <Notice tone="warning">Эту карточку только что удалили.</Notice>
        ))}
    </Dialog>
  );
}

function CardEditor({ board, card, onClose }: { board: Board; card: CardDetail; onClose: () => void }) {
  const update = useUpdateCard(board.id);
  const client = useQueryClient();
  const toast = useToast();
  const members = board.members.map((m) => m.user);
  const column = board.columns.find((c) => c.id === card.column_id);

  // Черновик описания помнит версию, с которой человек начал писать: по ней сервер поймёт,
  // не изменил ли карточку кто-то другой за это время
  const [draft, setDraft] = useState<{ text: string; base: number } | null>(null);
  const [conflict, setConflict] = useState<CardDetail | null>(null);
  const changedMeanwhile = draft !== null && card.version !== draft.base && conflict === null;

  const save = async (patch: Omit<CardPatch, 'version'>, version = card.version) => {
    try {
      const saved = await update.mutateAsync({ id: card.id, patch: { ...patch, version } });
      // Своя правка исполнителя или срока не должна считаться «чужим изменением» для черновика описания
      setDraft((d) => (d && d.base === version ? { ...d, base: saved.version } : d));
      return true;
    } catch (error) {
      if (error instanceof ApiError && error.code === 'version_conflict') {
        const current = error.details?.current as CardDetail | undefined;
        if (current) {
          client.setQueryData<CardDetail>(keys.card(card.id), (old) => old && { ...old, ...current });
          setConflict({ ...card, ...current });
        }
        return false;
      }
      toast({ text: errorMessage(error), tone: 'error' });
      return false;
    }
  };

  const saveDescription = async () => {
    if (!draft) return;
    if (await save({ description: draft.text }, draft.base)) {
      setDraft(null);
      setConflict(null);
    }
  };

  const overwrite = async () => {
    if (!draft || !conflict) return;
    if (await save({ description: draft.text }, conflict.version)) {
      setDraft(null);
      setConflict(null);
    }
  };

  const takeTheirs = () => {
    setDraft(null);
    setConflict(null);
  };

  const remove = async () => {
    if (!window.confirm(`Удалить карточку «${card.title}»?`)) return;
    try {
      await call(api.DELETE('/cards/{card_id}', { params: { path: { card_id: card.id } } }));
      client.setQueryData<Board>(
        keys.board(board.id),
        (b) => b && { ...b, cards: b.cards.filter((c) => c.id !== card.id) },
      );
      onClose();
      toast({ text: 'Карточка удалена' });
    } catch (error) {
      toast({ text: errorMessage(error), tone: 'error' });
    }
  };

  return (
    <div className={styles.editor}>
      <div className={styles.main}>
        <TitleField title={card.title} onSave={(title) => save({ title })} />
        <p className={styles.where}>
          в колонке <strong>{column?.title}</strong>
        </p>

        <section className={styles.section} aria-labelledby="description-label">
          <div className={styles.sectionHead}>
            <h3 id="description-label">Описание</h3>
            {draft === null && (
              <button
                type="button"
                className={styles.link}
                onClick={() => setDraft({ text: card.description, base: card.version })}
              >
                {card.description ? 'Изменить' : 'Добавить'}
              </button>
            )}
          </div>
          {draft === null ? (
            card.description ? (
              <p className={styles.description}>{card.description}</p>
            ) : (
              <p className={styles.empty}>Пока без описания</p>
            )
          ) : (
            <div className={styles.draft}>
              {changedMeanwhile && (
                <Notice tone="warning">
                  Пока вы писали, карточку изменили. При сохранении покажем обе версии.
                </Notice>
              )}
              {conflict && (
                <div className={styles.conflict} role="alert">
                  <p className={styles.conflictTitle}>Карточку успели изменить до вас</p>
                  <p className={styles.conflictLabel}>Сейчас сохранено:</p>
                  <blockquote>{conflict.description || 'Пустое описание'}</blockquote>
                  <div className={styles.row}>
                    <Button size="sm" variant="secondary" onClick={takeTheirs}>
                      Оставить сохранённое
                    </Button>
                    <Button size="sm" onClick={() => void overwrite()}>
                      Сохранить мою версию
                    </Button>
                  </div>
                </div>
              )}
              <textarea
                aria-label="Описание"
                value={draft.text}
                maxLength={5000}
                rows={6}
                autoFocus
                onChange={(e) => setDraft({ ...draft, text: e.target.value })}
              />
              {!conflict && (
                <div className={styles.row}>
                  <Button size="sm" onClick={() => void saveDescription()} loading={update.isPending}>
                    Сохранить
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setDraft(null)}>
                    Отмена
                  </Button>
                </div>
              )}
            </div>
          )}
        </section>

        <Attachments card={card} />
        <Comments card={card} />
      </div>

      <aside className={styles.side}>
        <label className={styles.sideField}>
          <span>Исполнитель</span>
          <select
            value={card.assignee_id ?? ''}
            onChange={(e) => void save({ assignee_id: e.target.value ? Number(e.target.value) : null })}
          >
            <option value="">Не назначен</option>
            {members.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.sideField}>
          <span>Срок</span>
          <input
            type="date"
            value={card.due_date ?? ''}
            onChange={(e) => void save({ due_date: e.target.value || null })}
          />
        </label>
        <p className={styles.meta}>
          Создана {timeAgo(card.created_at)}
          {card.created_by && members.find((m) => m.id === card.created_by) && (
            <> · {members.find((m) => m.id === card.created_by)?.name}</>
          )}
        </p>
        <Button variant="danger" size="sm" onClick={() => void remove()}>
          <Icon name="trash" size={16} /> Удалить карточку
        </Button>
      </aside>
    </div>
  );
}

function TitleField({ title, onSave }: { title: string; onSave: (title: string) => Promise<boolean> }) {
  const [value, setValue] = useState(title);
  const editing = useRef(false);
  useEffect(() => {
    if (!editing.current) setValue(title); // чужое переименование видно сразу, если человек сам не редактирует
  }, [title]);
  const commit = async () => {
    editing.current = false;
    const next = value.trim();
    if (!next) {
      setValue(title);
      return;
    }
    if (next !== title && !(await onSave(next))) setValue(title);
  };
  return (
    <textarea
      className={styles.title}
      aria-label="Название карточки"
      value={value}
      maxLength={200}
      rows={1}
      onFocus={() => (editing.current = true)}
      onChange={(e) => setValue(e.target.value.replace(/\n/g, ' '))}
      onBlur={() => void commit()}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          e.currentTarget.blur();
        }
      }}
    />
  );
}

// ---------- Вложения ----------

const MAX_BYTES = 5 * 1024 * 1024;

function Attachments({ card }: { card: CardDetail }) {
  const client = useQueryClient();
  const toast = useToast();
  const [uploads, setUploads] = useState<{ name: string; share: number }[]>([]);
  const [over, setOver] = useState(false);

  const add = async (files: FileList | null) => {
    for (const file of Array.from(files ?? [])) {
      if (file.size > MAX_BYTES) {
        toast({ text: `«${file.name}» больше 5 МБ`, tone: 'error' });
        continue;
      }
      setUploads((all) => [...all, { name: file.name, share: 0 }]);
      try {
        const attachment = await uploadFile(card.id, file, (share) =>
          setUploads((all) => all.map((u) => (u.name === file.name ? { ...u, share } : u))),
        );
        client.setQueryData<CardDetail>(keys.card(card.id), (old) =>
          old && !old.attachment_list.some((a) => a.id === attachment.id)
            ? {
                ...old,
                attachment_list: [...old.attachment_list, attachment],
                attachments: old.attachments + 1,
              }
            : old,
        );
      } catch (error) {
        toast({ text: `«${file.name}»: ${errorMessage(error)}`, tone: 'error' });
      } finally {
        setUploads((all) => all.filter((u) => u.name !== file.name));
      }
    }
  };

  const remove = async (attachment: Attachment) => {
    try {
      await call(
        api.DELETE('/attachments/{attachment_id}', { params: { path: { attachment_id: attachment.id } } }),
      );
      client.setQueryData<CardDetail>(
        keys.card(card.id),
        (old) =>
          old && {
            ...old,
            attachment_list: old.attachment_list.filter((a) => a.id !== attachment.id),
            attachments: Math.max(0, old.attachments - 1),
          },
      );
    } catch (error) {
      toast({ text: errorMessage(error), tone: 'error' });
    }
  };

  return (
    <section
      className={`${styles.section} ${over ? styles.dropping : ''}`}
      aria-labelledby="files-label"
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes('Files')) {
          e.preventDefault();
          setOver(true);
        }
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        void add(e.dataTransfer.files);
      }}
    >
      <div className={styles.sectionHead}>
        <h3 id="files-label">Файлы</h3>
        <label className={styles.link}>
          Прикрепить
          <input
            type="file"
            className="visually-hidden"
            multiple
            accept=".png,.jpg,.jpeg,.gif,.webp,.pdf,.txt,.csv,.md"
            onChange={(e) => {
              void add(e.currentTarget.files);
              e.currentTarget.value = '';
            }}
          />
        </label>
      </div>
      {card.attachment_list.length === 0 && uploads.length === 0 && (
        <p className={styles.empty}>Перетащите сюда файлы: картинки, PDF, текст. До 5 МБ.</p>
      )}
      <ul className={styles.files}>
        {card.attachment_list.map((a) => (
          <li key={a.id} className={styles.file} data-testid="attachment">
            <a href={fileUrl(a.url)} target="_blank" rel="noreferrer" className={styles.preview}>
              {a.thumbnail === 'ready' && a.thumbnail_url ? (
                <img src={fileUrl(a.thumbnail_url)} alt="" />
              ) : a.thumbnail === 'pending' ? (
                <span className={styles.pending}>превью…</span>
              ) : (
                <Icon name="file" size={28} />
              )}
            </a>
            <div className={styles.fileInfo}>
              <a href={fileUrl(a.url)} target="_blank" rel="noreferrer">
                {a.filename}
              </a>
              <span>{fileSize(a.size)}</span>
            </div>
            <button
              type="button"
              className={styles.remove}
              onClick={() => void remove(a)}
              aria-label={`Удалить ${a.filename}`}
            >
              <Icon name="trash" size={16} />
            </button>
          </li>
        ))}
        {uploads.map((u) => (
          <li key={u.name} className={styles.file}>
            <span className={styles.preview}>
              <Icon name="upload" size={24} />
            </span>
            <div className={styles.fileInfo}>
              <span>{u.name}</span>
              <progress value={u.share} max={1} aria-label={`Загрузка ${u.name}`} />
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ---------- Комментарии ----------

function Comments({ card }: { card: CardDetail }) {
  const client = useQueryClient();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  const submit = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const body = formText(form, 'body');
    if (!body) return;
    setBusy(true);
    try {
      const comment = await call(
        api.POST('/cards/{card_id}/comments', { params: { path: { card_id: card.id } }, body: { body } }),
      );
      client.setQueryData<CardDetail>(keys.card(card.id), (old) =>
        old && !old.comment_list.some((c) => c.id === comment.id)
          ? { ...old, comment_list: [...old.comment_list, comment], comments: old.comments + 1 }
          : old,
      );
      form.reset();
    } catch (error) {
      toast({ text: errorMessage(error), tone: 'error' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={styles.section} aria-labelledby="comments-label">
      <h3 id="comments-label">Обсуждение</h3>
      <ol className={styles.comments}>
        {card.comment_list.map((c) => (
          <li key={c.id} className={styles.comment}>
            {c.author ? <Avatar user={c.author} size="sm" /> : <span className={styles.ghost} />}
            <div>
              <p className={styles.commentHead}>
                <strong>{c.author?.name ?? 'Бывший участник'}</strong>{' '}
                <time dateTime={c.created_at}>{timeAgo(c.created_at)}</time>
              </p>
              <p className={styles.commentBody}>{c.body}</p>
            </div>
          </li>
        ))}
      </ol>
      <form className={styles.commentForm} onSubmit={submit}>
        <textarea
          name="body"
          aria-label="Новый комментарий"
          placeholder="Написать комментарий…"
          maxLength={2000}
          rows={2}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) e.currentTarget.form?.requestSubmit();
          }}
        />
        <Button type="submit" size="sm" loading={busy}>
          Отправить
        </Button>
      </form>
    </section>
  );
}
