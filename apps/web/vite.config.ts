import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const appDirectory = dirname(fileURLToPath(import.meta.url));
const repositoryDirectory = resolve(appDirectory, '../..');

export default defineConfig({
  plugins: [react()],
  publicDir: resolve(repositoryDirectory, 'fixtures/device'),
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    fs: {
      allow: [repositoryDirectory],
    },
  },
  build: {
    outDir: resolve(appDirectory, 'dist'),
    emptyOutDir: true,
  },
});
