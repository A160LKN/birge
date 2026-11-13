import { BoardSocket, PING_EVERY, PONG_TIMEOUT, reconnectDelay, type SocketOptions } from './socket';

/** Поддельный WebSocket: тест сам решает, когда сервер ответил, а когда связь оборвалась. */
class FakeSocket {
  static OPEN = 1;
  static instances: FakeSocket[] = [];
  readyState = 0;
  sent: Record<string, unknown>[] = [];
  closedWith: number | null = null;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(JSON.parse(data) as Record<string, unknown>);
  }
  close(code = 1000) {
    this.closedWith = code;
  }
  // Действия «сервера»
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  receive(message: object) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
  drop(code: number) {
    this.readyState = 3;
    this.onclose?.({ code });
  }
}

const latest = () => FakeSocket.instances.at(-1) as FakeSocket;
const event = (id: number) => ({
  type: 'card.deleted',
  id,
  board_id: 5,
  actor_id: 2,
  client_id: null,
  data: { id: 1, column_id: 10 },
});

function setup(overrides: Partial<SocketOptions> = {}) {
  const options = {
    url: 'ws://api/ws/boards/5',
    token: () => 'token-1',
    lastEventId: 40,
    onEvent: vi.fn(),
    onPresence: vi.fn(),
    onStatus: vi.fn(),
    onResync: vi.fn(),
    onClosed: vi.fn(),
    ...overrides,
  } satisfies SocketOptions;
  const socket = new BoardSocket(options);
  socket.start();
  return { socket, options };
}

beforeEach(() => {
  FakeSocket.instances = [];
  vi.stubGlobal('WebSocket', FakeSocket);
  vi.useFakeTimers();
  vi.spyOn(Math, 'random').mockReturnValue(1); // без разброса — паузы предсказуемы
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it('токен уходит первым сообщением вместе с номером последнего события, не в адресе', () => {
  setup();
  latest().open();
  expect(latest().url).toBe('ws://api/ws/boards/5');
  expect(latest().sent[0]).toEqual({ type: 'auth', token: 'token-1', last_event_id: 40 });
});

it('ready — «в сети» и список тех, кто на доске', () => {
  const { options } = setup();
  latest().open();
  latest().receive({ type: 'ready', user_id: 1, presence: [1, 2] });
  expect(options.onStatus).toHaveBeenLastCalledWith('online');
  expect(options.onPresence).toHaveBeenCalledWith([1, 2]);
});

it('одно событие дважды применяется один раз', () => {
  const { options, socket } = setup();
  latest().open();
  latest().receive(event(41));
  latest().receive(event(41));
  latest().receive(event(42));
  expect(options.onEvent).toHaveBeenCalledTimes(2);
  expect(socket.position).toBe(42);
});

it('после обрыва переподключается с растущей паузой и догоняет с последнего события', () => {
  const { options } = setup();
  latest().open();
  latest().receive({ type: 'ready', user_id: 1, presence: [] });
  latest().receive(event(45));

  latest().drop(1006);
  expect(options.onStatus).toHaveBeenLastCalledWith('reconnecting');
  vi.advanceTimersByTime(999);
  expect(FakeSocket.instances).toHaveLength(1);
  vi.advanceTimersByTime(1);
  expect(FakeSocket.instances).toHaveLength(2);

  latest().drop(1006); // и второй раз не вышло — пауза вдвое больше
  vi.advanceTimersByTime(1999);
  expect(FakeSocket.instances).toHaveLength(2);
  vi.advanceTimersByTime(1);
  latest().open();
  expect(latest().sent[0]).toMatchObject({ last_event_id: 45 });
});

it('пауза растёт до 15 секунд и имеет разброс', () => {
  expect([0, 1, 2, 3, 4, 10].map((n) => reconnectDelay(n, () => 1))).toEqual([
    1000, 2000, 4000, 8000, 15000, 15000,
  ]);
  expect(reconnectDelay(0, () => 0)).toBe(500);
});

it.each([
  [4401, 'unauthorized'],
  [4403, 'removed'],
  [4404, 'gone'],
])('код %d — закрыто навсегда (%s), без переподключения', (code, reason) => {
  const { options } = setup();
  latest().open();
  latest().drop(code);
  vi.advanceTimersByTime(60_000);
  expect(options.onClosed).toHaveBeenCalledWith(reason);
  expect(FakeSocket.instances).toHaveLength(1);
});

it('нет ответа на ping — соединение считается зависшим и переоткрывается', () => {
  setup();
  latest().open();
  latest().receive({ type: 'ready', user_id: 1, presence: [] });
  vi.advanceTimersByTime(PING_EVERY);
  expect(latest().sent.at(-1)).toEqual({ type: 'ping' });
  vi.advanceTimersByTime(PONG_TIMEOUT);
  expect(latest().closedWith).toBe(4000);
});

it('pong вовремя — соединение живо', () => {
  setup();
  latest().open();
  latest().receive({ type: 'ready', user_id: 1, presence: [] });
  vi.advanceTimersByTime(PING_EVERY);
  latest().receive({ type: 'pong' });
  vi.advanceTimersByTime(PONG_TIMEOUT);
  expect(latest().closedWith).toBeNull();
});

it('без интернета ждёт события online, а не стучится в сервер', () => {
  const { options } = setup();
  latest().open();
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);
  latest().drop(1006);
  expect(options.onStatus).toHaveBeenLastCalledWith('offline');
  vi.advanceTimersByTime(60_000);
  expect(FakeSocket.instances).toHaveLength(1);
  window.dispatchEvent(new Event('online'));
  expect(FakeSocket.instances).toHaveLength(2);
});

it('resync — просит перезагрузить доску, resume продолжает с нового номера', () => {
  const { options, socket } = setup();
  latest().open();
  latest().receive({ type: 'resync' });
  expect(options.onResync).toHaveBeenCalled();
  socket.resume(900);
  latest().open();
  expect(latest().sent[0]).toMatchObject({ last_event_id: 900 });
});

it('stop закрывает соединение и больше не переподключается', () => {
  const { socket } = setup();
  latest().open();
  socket.stop();
  expect(latest().closedWith).toBe(1000);
  latest().drop(1000);
  vi.advanceTimersByTime(60_000);
  expect(FakeSocket.instances).toHaveLength(1);
});

it('без токена не подключается и сообщает о выходе', () => {
  const { options } = setup({ token: () => null });
  latest().open();
  expect(options.onClosed).toHaveBeenCalledWith('unauthorized');
  expect(latest().sent).toEqual([]);
});
