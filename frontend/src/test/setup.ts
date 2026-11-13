import '@testing-library/jest-dom/vitest';
import './matchMedia';
import { cleanup } from '@testing-library/react';
import { server } from './server';

// jsdom не умеет <dialog>.showModal — достаточно открыть его
HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
  this.setAttribute('open', '');
};
HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
  this.removeAttribute('open');
};

// Любой запрос, который тест не описал, — ошибка теста, а не тихий поход в сеть
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  cleanup();
  localStorage.clear();
});
afterAll(() => server.close());
