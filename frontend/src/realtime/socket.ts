/**
 * Соединение с доской по WebSocket: авторизация первым сообщением, догонялка пропущенного,
 * переподключение с растущей паузой, проверка «жив ли сервер» через ping.
 *
 * Класс не знает про React — его можно проверить тестами с поддельным сервером.
 */
import type { BoardEvent, ServerMessage } from './events';

export type SocketStatus = 'connecting' | 'online' | 'reconnecting' | 'offline';
export type CloseReason = 'unauthorized' | 'removed' | 'gone';

export interface SocketOptions {
  url: string;
  token: () => string | null;
  lastEventId: number;
  onEvent: (event: BoardEvent) => void;
  onPresence: (users: number[]) => void;
  onStatus: (status: SocketStatus) => void;
  /** Пропущено слишком много — нужно перезагрузить доску и вызвать resume() с новым номером */
  onResync: () => void;
  /** Подключение закрыто навсегда: вход истёк, участника удалили или доски больше нет */
  onClosed: (reason: CloseReason) => void;
}

export const PING_EVERY = 25_000;
export const PONG_TIMEOUT = 10_000;
export const MAX_DELAY = 15_000;

const FINAL_CODES: Record<number, CloseReason> = { 4401: 'unauthorized', 4403: 'removed', 4404: 'gone' };

/** Пауза перед повтором: 1, 2, 4, 8… до 15 секунд, со случайным разбросом — чтобы после сбоя
 * сотни вкладок не стучались в сервер в одну и ту же секунду. */
export const reconnectDelay = (attempt: number, random: () => number = Math.random) =>
  Math.min(MAX_DELAY, 1000 * 2 ** attempt) * (0.5 + random() / 2);

export class BoardSocket {
  private ws: WebSocket | null = null;
  private stopped = false;
  private attempt = 0;
  private lastEventId: number;
  private readonly seen = new Set<number>();
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private pingTimer: ReturnType<typeof setInterval> | undefined;
  private pongTimer: ReturnType<typeof setTimeout> | undefined;

  constructor(private readonly options: SocketOptions) {
    this.lastEventId = options.lastEventId;
  }

  start() {
    this.stopped = false;
    window.addEventListener('online', this.handleOnline);
    this.connect();
  }

  stop() {
    this.stopped = true;
    window.removeEventListener('online', this.handleOnline);
    this.clearTimers();
    this.ws?.close(1000);
    this.ws = null;
  }

  /** После перезагрузки доски: продолжить с её last_event_id. */
  resume(lastEventId: number) {
    this.lastEventId = Math.max(this.lastEventId, lastEventId);
    this.reconnectNow();
  }

  get position() {
    return this.lastEventId;
  }

  private connect() {
    this.options.onStatus(this.attempt === 0 ? 'connecting' : 'reconnecting');
    const ws = new WebSocket(this.options.url);
    this.ws = ws;
    ws.onopen = () => {
      const token = this.options.token();
      if (token === null) {
        this.options.onClosed('unauthorized');
        this.stop();
        return;
      }
      // Токен — в первом сообщении, а не в адресе: адреса оседают в логах
      ws.send(JSON.stringify({ type: 'auth', token, last_event_id: this.lastEventId }));
    };
    ws.onmessage = (message: MessageEvent<string>) => {
      if (ws === this.ws) this.handle(JSON.parse(message.data) as ServerMessage);
    };
    ws.onclose = (event: CloseEvent) => {
      if (ws === this.ws) this.handleClose(event.code);
    };
  }

  private handle(message: ServerMessage) {
    switch (message.type) {
      case 'ready':
        this.attempt = 0;
        this.options.onStatus('online');
        this.options.onPresence(message.presence);
        this.startHeartbeat();
        return;
      case 'presence':
        this.options.onPresence(message.users);
        return;
      case 'pong':
        clearTimeout(this.pongTimer);
        return;
      case 'resync':
        this.options.onResync();
        return;
      case 'error':
        return;
      default:
        // Одно событие может прийти дважды (догонялка и живая рассылка) — применяем один раз
        if (this.seen.has(message.id)) return;
        this.seen.add(message.id);
        this.lastEventId = Math.max(this.lastEventId, message.id);
        this.options.onEvent(message);
    }
  }

  private handleClose(code: number) {
    this.clearTimers();
    this.ws = null;
    if (this.stopped) return;
    const reason = FINAL_CODES[code];
    if (reason) {
      this.stopped = true;
      this.options.onClosed(reason);
      return;
    }
    if (!navigator.onLine) {
      this.options.onStatus('offline'); // ждём события online, а не долбим сервер впустую
      return;
    }
    this.options.onStatus('reconnecting');
    this.retryTimer = setTimeout(() => this.connect(), reconnectDelay(this.attempt));
    this.attempt += 1;
  }

  private readonly handleOnline = () => {
    if (!this.stopped && this.ws === null) this.reconnectNow();
  };

  private reconnectNow() {
    this.clearTimers();
    const old = this.ws;
    this.ws = null;
    old?.close(1000);
    this.attempt = Math.max(this.attempt, 1);
    if (!this.stopped) this.connect();
  }

  private startHeartbeat() {
    clearInterval(this.pingTimer);
    this.pingTimer = setInterval(() => {
      if (this.ws?.readyState !== WebSocket.OPEN) return;
      this.ws.send(JSON.stringify({ type: 'ping' }));
      clearTimeout(this.pongTimer);
      // Нет ответа — соединение «зависло» (бывает в мобильных сетях): рвём и подключаемся заново
      this.pongTimer = setTimeout(() => this.ws?.close(4000), PONG_TIMEOUT);
    }, PING_EVERY);
  }

  private clearTimers() {
    clearTimeout(this.retryTimer);
    clearInterval(this.pingTimer);
    clearTimeout(this.pongTimer);
  }
}
