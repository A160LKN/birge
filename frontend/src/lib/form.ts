/** Текстовое поле формы без пробелов по краям; файл или отсутствующее поле — пустая строка. */
export function formText(form: HTMLFormElement, name: string): string {
  const value = new FormData(form).get(name);
  return typeof value === 'string' ? value.trim() : '';
}
