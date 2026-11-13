import { tokenStore } from '@/auth/token';
import { API_URL, CLIENT_ID, type Attachment } from './client';
import { ApiError, toApiError } from './errors';

/** Загрузка через XMLHttpRequest: у fetch нет прогресса отправки, а файл до 5 МБ на мобильном идёт заметно. */
export function uploadFile(
  cardId: number,
  file: File,
  onProgress: (share: number) => void,
): Promise<Attachment> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_URL}/cards/${cardId}/attachments`);
    const token = tokenStore.get();
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.setRequestHeader('X-Client-Id', CLIENT_ID);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* пустой или не JSON ответ */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as Attachment);
      else reject(toApiError(xhr.status, body));
    };
    xhr.onerror = () => reject(new ApiError(0, 'network', 'Нет связи с сервером. Файл не загружен'));
    const form = new FormData();
    form.append('file', file);
    xhr.send(form);
  });
}
