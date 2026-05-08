import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    pool: 'threads',
    poolOptions: {
      threads: {
        minThreads: 1,
        maxThreads: 8
      }
    }
  }
});
