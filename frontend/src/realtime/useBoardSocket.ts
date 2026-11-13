import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { API_URL, CLIENT_ID, type Activity, type Board, type CardDetail } from '@/api/client';
import { keys } from '@/api/queries';
import { tokenStore } from '@/auth/token';
import { useToast } from '@/components/Toaster';
import { applyToActivity, applyToBoard, applyToCard, cardOf, type BoardEvent } from './events';
import { BoardSocket, type SocketStatus } from './socket';

export const FLASH_MS = 2600;

/** Выгрузки, которые запросили из этой вкладки: о готовности остальных сообщать не нужно. */
const myExports = new Map<number, (event: BoardEvent & { type: 'export.updated' }) => void>();
export function watchExport(id: number, onReady: (event: BoardEvent & { type: 'export.updated' }) => void) {
  myExports.set(id, onReady);
}

export const socketUrl = (boardId: number) => `${API_URL.replace(/^http/, 'ws')}/ws/boards/${boardId}`;

export interface Live {
  status: SocketStatus;
  presence: number[];
  /** Карточки, которые только что изменил кто-то другой: id карточки → id автора */
  flashes: ReadonlyMap<number, number>;
}

/** Живая доска: события WebSocket сразу применяются к кешу TanStack Query. */
export function useBoardSocket(board: Board | undefined): Live {
  const client = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const [status, setStatus] = useState<SocketStatus>('connecting');
  const [presence, setPresence] = useState<number[]>([]);
  const [flashes, setFlashes] = useState<ReadonlyMap<number, number>>(new Map());
  const socket = useRef<BoardSocket | null>(null);
  const boardId = board?.id;
  const title = useRef(board?.title);
  title.current = board?.title;
  const loaded = board !== undefined;
  const startFrom = useRef(board?.last_event_id ?? 0);
  if (board && !socket.current) startFrom.current = board.last_event_id;

  useEffect(() => {
    if (boardId === undefined || !loaded) return;

    const flash = (cardId: number, actorId: number) => {
      setFlashes((current) => new Map(current).set(cardId, actorId));
      setTimeout(() => {
        setFlashes((current) => {
          if (current.get(cardId) !== actorId) return current;
          const next = new Map(current);
          next.delete(cardId);
          return next;
        });
      }, FLASH_MS);
    };

    const onEvent = (event: BoardEvent) => {
      client.setQueryData<Board>(keys.board(boardId), (current) => current && applyToBoard(current, event));
      const cardId = cardOf(event);
      if (cardId !== null) {
        client.setQueryData<CardDetail>(
          keys.card(cardId),
          (current) => current && applyToCard(current, event),
        );
      }
      client.setQueryData<Activity[]>(keys.activity(boardId), (feed) => feed && applyToActivity(feed, event));

      const remote = event.client_id !== CLIENT_ID && event.actor_id !== null;
      if (
        remote &&
        (event.type === 'card.created' || event.type === 'card.moved' || event.type === 'card.updated')
      ) {
        flash(event.data.id, event.actor_id ?? 0);
      }
      if (
        event.type === 'board.updated' ||
        event.type === 'member.added' ||
        event.type === 'member.removed'
      ) {
        void client.invalidateQueries({ queryKey: keys.boards });
      }
      if (event.type === 'export.updated') {
        const done = myExports.get(event.data.id);
        if (done && event.data.status !== 'pending') {
          myExports.delete(event.data.id);
          done(event);
        }
      }
    };

    const instance = new BoardSocket({
      url: socketUrl(boardId),
      token: tokenStore.get,
      lastEventId: startFrom.current,
      onEvent,
      onPresence: setPresence,
      onStatus: setStatus,
      onResync: () => {
        void client
          .refetchQueries({ queryKey: keys.board(boardId), exact: true })
          .catch(() => undefined)
          .then(() => {
            const fresh = client.getQueryData<Board>(keys.board(boardId));
            instance.resume(fresh?.last_event_id ?? instance.position);
          });
      },
      onClosed: (reason) => {
        if (reason === 'unauthorized') {
          tokenStore.set(null);
          return;
        }
        client.removeQueries({ queryKey: keys.board(boardId) });
        void client.invalidateQueries({ queryKey: keys.boards });
        toast({
          text:
            reason === 'removed'
              ? `Вас удалили с доски «${title.current ?? ''}»`
              : `Доску «${title.current ?? ''}» удалили`,
        });
        void navigate('/', { replace: true });
      },
    });
    socket.current = instance;
    instance.start();
    return () => {
      instance.stop();
      socket.current = null;
    };
  }, [boardId, loaded, client, navigate, toast]);

  return { status, presence, flashes };
}
