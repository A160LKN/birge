import vectors from '../../../shared/position-vectors.json';
import { dueInfo, fileSize, timeAgo } from './dates';
import { initials, personColor, PEOPLE_COLORS } from './people';
import { compareKeys, keyBetween } from './positions';

describe('позиции', () => {
  it('совпадают с сервером на общих примерах', () => {
    // Те же примеры проверяет бэкенд: мгновенный перенос в браузере даёт тот же ключ, что сервер
    for (const [before, after, expected] of vectors.cases as [string | null, string | null, string][]) {
      expect(keyBetween(before, after)).toBe(expected);
    }
  });

  it('сортировка побайтная, как COLLATE "C", а не по правилам языка', () => {
    expect(['a', 'B', 'Z', 'b'].sort(compareKeys)).toEqual(['B', 'Z', 'a', 'b']);
    expect('a'.localeCompare('B', 'ru')).toBeLessThan(0); // а localeCompare поставил бы «a» раньше «B»
  });

  it('отказывается от ключей не по порядку', () => {
    expect(() => keyBetween('W', 'V')).toThrow();
  });
});

describe('люди', () => {
  it('цвет зависит только от id и одинаков у всех', () => {
    expect(personColor(1)).toBe(PEOPLE_COLORS[0]);
    expect(personColor(1 + PEOPLE_COLORS.length)).toBe(PEOPLE_COLORS[0]);
    expect(personColor(2)).not.toBe(personColor(1));
  });

  it.each([
    ['Алия', 'А'],
    ['Алия Сейткали', 'АС'],
    ['  бауыржан  ', 'Б'],
    ['', '?'],
  ])('инициалы «%s» → %s', (name, expected) => expect(initials(name)).toBe(expected));
});

describe('даты и размеры', () => {
  const today = new Date(2026, 10, 13);
  it.each([
    ['2026-11-10', 'просрочено на 3 дн.', 'overdue'],
    ['2026-11-13', 'сегодня', 'soon'],
    ['2026-11-14', 'завтра', 'soon'],
    ['2026-12-01', '1 дек', 'later'],
  ])('срок %s → %s', (due, label, tone) => expect(dueInfo(due, today)).toEqual({ label, tone }));

  it('время назад', () => {
    const now = new Date('2026-11-13T12:00:00Z');
    expect(timeAgo('2026-11-13T11:59:40Z', now)).toBe('только что');
    expect(timeAgo('2026-11-13T11:30:00Z', now)).toBe('30 мин назад');
    expect(timeAgo('2026-11-13T09:00:00Z', now)).toBe('3 ч назад');
  });

  it.each([
    [500, '500 Б'],
    [2048, '2 КБ'],
    [1.5 * 1024 * 1024, '1,5 МБ'],
  ])('размер %d → %s', (bytes, text) => expect(fileSize(bytes)).toBe(text));
});
