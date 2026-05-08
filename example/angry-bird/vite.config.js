import { defineConfig } from 'vite';

export default defineConfig({
  envPrefix: ['VITE_', 'ANGRY_BIRD_'],
  server: {
    port: 4100
  },
  preview: {
    port: 4101
  }
});
