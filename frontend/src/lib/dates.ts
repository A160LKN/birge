const DAY = 24 * 60 * 60 * 1000;

/** Срок карточки: «сегодня», «завтра», «просрочено на 2 дн.» — и тон для цвета. */
export function dueInfo(
  due: string,
  today: Date = new Date(),
): { label: string; tone: 'overdue' | 'soon' | 'later' } {
  const [y, m, d] = due.split('-').map(Number) as [number, number, number];
  const target = Date.UTC(y, m - 1, d);
  const now = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  const days = Math.round((target - now) / DAY);
  if (days < 0) return { label: `просрочено на ${-days} дн.`, tone: 'overdue' };
  if (days === 0) return { label: 'сегодня', tone: 'soon' };
  if (days === 1) return { label: 'завтра', tone: 'soon' };
  const label = new Date(target).toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  });
  return { label: label.replace('.', ''), tone: 'later' };
}

export function timeAgo(iso: string, now: Date = new Date()): string {
  const seconds = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 1000));
  if (seconds < 45) return 'только что';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} мин назад`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} ч назад`;
  return new Date(iso).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });
}

export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} МБ`;
}
