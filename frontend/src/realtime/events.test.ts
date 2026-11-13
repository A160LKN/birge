import type { Activity } from '@/api/client';
import { bauyrzhan, board, card, detail, member } from '@/test/server';
import { applyToActivity, applyToBoard, applyToCard, cardOf, type BoardEvent } from './events';

let nextId = 100;
const event = (type: BoardEvent['type'], data: unknown): BoardEvent =>
  ({ type, data, id: nextId++, board_id: 5, actor_id: 2, client_id: null }) as BoardEvent;

describe('события → доска', () => {
  it('новая карточка появляется, повторное событие ничего не дублирует', () => {
    const created = event('card.created', card({ id: 9, title: 'Новая' }));
    const once = applyToBoard(board(), created);
    const twice = applyToBoard(once, created);
    expect(once.cards.map((c) => c.id)).toEqual([1, 2, 9]);
    expect(twice).toEqual(once);
  });

  it('перенос меняет колонку и позицию', () => {
    const moved = applyToBoard(
      board(),
      event('card.moved', card({ column_id: 12, position: 'z', updated_at: '2026-11-13T09:00:00Z' })),
    );
    expect(moved.cards.find((c) => c.id === 1)).toMatchObject({ column_id: 12, position: 'z' });
  });

  it('устаревшее событие не откатывает свежие данные', () => {
    const fresh = applyToBoard(board(), event('card.updated', card({ title: 'v3', version: 3 })));
    const stale = applyToBoard(fresh, event('card.updated', card({ title: 'v2', version: 2 })));
    expect(stale.cards.find((c) => c.id === 1)?.title).toBe('v3');
  });

  it('перенос без смены версии сравнивается по времени изменения', () => {
    const later = card({ position: 'z', updated_at: '2026-11-13T10:00:00Z' });
    const earlier = card({ position: 'a', updated_at: '2026-11-13T09:00:00Z' });
    const result = applyToBoard(
      applyToBoard(board(), event('card.moved', later)),
      event('card.moved', earlier),
    );
    expect(result.cards.find((c) => c.id === 1)?.position).toBe('z');
  });

  it('карточка в неизвестную колонку игнорируется', () => {
    expect(applyToBoard(board(), event('card.created', card({ id: 9, column_id: 999 }))).cards).toHaveLength(
      2,
    );
  });

  it('удаление колонки убирает и её карточки', () => {
    const result = applyToBoard(board(), event('column.deleted', { id: 10 }));
    expect(result.columns.map((c) => c.id)).toEqual([11, 12]);
    expect(result.cards.map((c) => c.id)).toEqual([]);
  });

  it('новая и переименованная колонка', () => {
    const added = applyToBoard(board(), event('column.created', { id: 13, title: 'QA', position: 'v' }));
    const renamed = applyToBoard(added, event('column.updated', { id: 13, title: 'Тесты', position: 'v' }));
    expect(renamed.columns.at(-1)).toEqual({ id: 13, title: 'Тесты', position: 'v' });
  });

  it('ушедший участник: исчезает из списка, его карточки без исполнителя и с новой версией', () => {
    const result = applyToBoard(board(), event('member.removed', { user_id: 2, unassigned: [2] }));
    expect(result.members.map((m) => m.user.id)).toEqual([1]);
    expect(result.cards.find((c) => c.id === 2)).toMatchObject({ assignee_id: null, version: 2 });
  });

  it('новый участник добавляется один раз', () => {
    const newcomer = member({ id: 3, email: 'k@test.kz', name: 'Карина' });
    const once = applyToBoard(board(), event('member.added', newcomer));
    expect(applyToBoard(once, event('member.added', newcomer)).members).toHaveLength(3);
  });

  it('комментарии и файлы меняют счётчики на карточке', () => {
    let result = applyToBoard(
      board(),
      event('comment.created', { id: 1, card_id: 1, body: 'x', author: bauyrzhan, created_at: '' }),
    );
    result = applyToBoard(result, event('attachment.created', { id: 7, card_id: 1 }));
    result = applyToBoard(result, event('attachment.deleted', { id: 7, card_id: 1 }));
    expect(result.cards.find((c) => c.id === 1)).toMatchObject({ comments: 1, attachments: 0 });
  });

  it('переименование доски и удаление карточки', () => {
    let result = applyToBoard(board(), event('board.updated', { title: 'Релиз' }));
    result = applyToBoard(result, event('card.deleted', { id: 1, column_id: 10 }));
    expect(result.title).toBe('Релиз');
    expect(result.cards.map((c) => c.id)).toEqual([2]);
  });
});

describe('события → открытая карточка', () => {
  it('комментарий добавляется один раз', () => {
    const comment = event('comment.created', {
      id: 5,
      card_id: 1,
      body: 'Готово',
      author: bauyrzhan,
      created_at: '',
    });
    const once = applyToCard(detail(), comment);
    expect(applyToCard(once, comment).comment_list).toHaveLength(1);
    expect(once.comments).toBe(1);
  });

  it('превью файла обновляется на месте', () => {
    const file = {
      id: 7,
      card_id: 1,
      filename: 'a.png',
      content_type: 'image/png',
      size: 10,
      thumbnail: 'pending',
      uploader_id: 1,
      created_at: '',
      url: '/f',
      thumbnail_url: null,
    };
    const added = applyToCard(detail(), event('attachment.created', file));
    const ready = applyToCard(
      added,
      event('attachment.updated', { ...file, thumbnail: 'ready', thumbnail_url: '/t' }),
    );
    expect(ready.attachment_list).toEqual([{ ...file, thumbnail: 'ready', thumbnail_url: '/t' }]);
    expect(ready.attachments).toBe(1);
    expect(applyToCard(ready, event('attachment.deleted', { id: 7, card_id: 1 })).attachment_list).toEqual(
      [],
    );
  });

  it('события чужих карточек не трогают открытую', () => {
    const other = event('card.updated', card({ id: 2, title: 'Другая', version: 5 }));
    expect(applyToCard(detail(), other)).toEqual(detail());
  });

  it('поля карточки обновляются', () => {
    expect(applyToCard(detail(), event('card.updated', card({ title: 'Новое', version: 2 }))).title).toBe(
      'Новое',
    );
  });

  it('cardOf знает, какую карточку затрагивает событие', () => {
    expect(cardOf(event('comment.created', { id: 1, card_id: 7 }))).toBe(7);
    expect(cardOf(event('column.deleted', { id: 1 }))).toBeNull();
  });
});

it('лента: новое сверху, без повторов', () => {
  const activity: Activity = {
    id: 3,
    kind: 'card.created',
    message: 'Новая карточка',
    actor: null,
    created_at: '',
  };
  const withActivity = event('card.created', { ...card(), activity });
  const feed = applyToActivity([], withActivity);
  expect(applyToActivity(feed, withActivity)).toEqual([activity]);
  expect(applyToActivity(feed, event('card.deleted', { id: 1, column_id: 10 }))).toBe(feed);
});
