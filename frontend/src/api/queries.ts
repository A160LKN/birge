import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError } from './errors';
import { api, call, type Board, type Card, type CardDetail, type CardPatch, type Column } from './client';

export const keys = {
  me: ['me'] as const,
  boards: ['boards'] as const,
  board: (id: number) => ['board', id] as const,
  card: (id: number) => ['card', id] as const,
  activity: (boardId: number) => ['activity', boardId] as const,
};

const retry = (count: number, error: unknown) =>
  // 4xx повтором не исправить, а сбой сети или сервера — можно
  count < 2 && !(error instanceof ApiError && error.status >= 400 && error.status < 500);

export const useBoards = () =>
  useQuery({ queryKey: keys.boards, queryFn: () => call(api.GET('/boards')), retry });

export const useBoard = (id: number) =>
  useQuery({
    queryKey: keys.board(id),
    queryFn: () => call(api.GET('/boards/{board_id}', { params: { path: { board_id: id } } })),
    retry,
    // Доску держат в актуальном состоянии события WebSocket — лишние перезапросы не нужны
    staleTime: Infinity,
  });

export const useCard = (id: number | null) =>
  useQuery({
    queryKey: keys.card(id ?? 0),
    queryFn: () => call(api.GET('/cards/{card_id}', { params: { path: { card_id: id ?? 0 } } })),
    enabled: id !== null,
    retry,
  });

export const useActivity = (boardId: number, enabled: boolean) =>
  useQuery({
    queryKey: keys.activity(boardId),
    queryFn: () =>
      call(api.GET('/boards/{board_id}/activity', { params: { path: { board_id: boardId }, query: {} } })),
    enabled,
    retry,
  });

export function useCreateBoard() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (title: string) => call(api.POST('/boards', { body: { title } })),
    onSuccess: (board) => {
      client.setQueryData(keys.board(board.id), board);
      void client.invalidateQueries({ queryKey: keys.boards });
    },
  });
}

/** Обновить карточку в кеше доски (и в открытой карточке) — общий помощник для мутаций и событий. */
export function putCard(board: Board, card: Card): Board {
  const others = board.cards.filter((c) => c.id !== card.id);
  return { ...board, cards: [...others, card] };
}

export function useUpdateCard(boardId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: CardPatch }) =>
      call(api.PATCH('/cards/{card_id}', { params: { path: { card_id: id } }, body: patch })),
    onSuccess: (card) => {
      client.setQueryData<Board>(keys.board(boardId), (board) => (board ? putCard(board, card) : board));
      client.setQueryData<CardDetail>(keys.card(card.id), (detail) =>
        detail ? { ...detail, ...card } : detail,
      );
    },
  });
}

export function useCreateCard(boardId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { column_id: number; title: string }) => call(api.POST('/cards', { body })),
    onSuccess: (card) =>
      client.setQueryData<Board>(keys.board(boardId), (board) => (board ? putCard(board, card) : board)),
  });
}

export function useCreateColumn(boardId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (title: string) =>
      call(
        api.POST('/boards/{board_id}/columns', { params: { path: { board_id: boardId } }, body: { title } }),
      ),
    onSuccess: (column: Column) =>
      client.setQueryData<Board>(keys.board(boardId), (board) =>
        board && !board.columns.some((c) => c.id === column.id)
          ? { ...board, columns: [...board.columns, column] }
          : board,
      ),
  });
}
