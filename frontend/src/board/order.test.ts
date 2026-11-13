import { board, card } from '@/test/server';
import { lanesOf, moveInLanes, planMove } from './order';

const b = board({
  cards: [
    card({ id: 1, position: 'V' }),
    card({ id: 2, position: 'k' }),
    card({ id: 3, position: 'B' }),
    card({ id: 4, column_id: 11, position: 'V' }),
  ],
});

it('карточки по колонкам в порядке ключей (побайтно: «B» раньше «V» и «k»)', () => {
  expect(lanesOf(b)).toEqual({ 10: [3, 1, 2], 11: [4], 12: [] });
});

it('равные ключи упорядочены по id — как на сервере', () => {
  const tie = board({ cards: [card({ id: 7, position: 'V' }), card({ id: 5, position: 'V' })] });
  expect(lanesOf(tie)[10]).toEqual([5, 7]);
});

it('перенос в другую колонку на нужное место', () => {
  expect(moveInLanes(lanesOf(b), 1, 11, 0)).toEqual({ 10: [3, 2], 11: [1, 4], 12: [] });
  expect(moveInLanes(lanesOf(b), 1, 12, 99)).toEqual({ 10: [3, 2], 11: [4], 12: [1] });
});

it('план переноса: запрос «после кого» и мгновенная позиция между соседями', () => {
  const plan = planMove(b, moveInLanes(lanesOf(b), 2, 11, 1), 2);
  expect(plan?.request).toEqual({ column_id: 11, after_id: 4 });
  expect(plan?.optimistic).toMatchObject({ id: 2, column_id: 11 });
  expect(plan && plan.optimistic.position > 'V').toBe(true);
});

it('наверх колонки — after_id null', () => {
  const plan = planMove(b, moveInLanes(lanesOf(b), 2, 10, 0), 2);
  expect(plan?.request).toEqual({ column_id: 10, after_id: null });
  expect(plan && plan.optimistic.position < 'B').toBe(true);
});

it('карточку отпустили на прежнем месте — запроса нет', () => {
  expect(planMove(b, lanesOf(b), 1)).toBeNull();
});
