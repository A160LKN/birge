/// <reference types="vitest/config" />
import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: { port: 5173 },
  preview: { port: 4173 },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: { modules: { classNameStrategy: 'non-scoped' } },
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.test.{ts,tsx}', 'src/test/**', 'src/api/schema.d.ts', 'src/main.tsx'],
      // Перетаскивание мышью и тачем проверяют E2E-тесты в настоящем браузере; порог не даёт покрытию проседать
      // Vitest 5 считает ветки строже прежнего (каждый ?. и ?? — ветка), поэтому порог веток ниже
      thresholds: { lines: 75, branches: 70, functions: 75 },
    },
  },
});
