/// <reference types="node" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'
import { readFileSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))

// Reason: loadEnv can be unreliable on Windows; parse .env.local directly
function getApiPort(): string {
  const envPath = join(__dirname, '.env.local')
  if (existsSync(envPath)) {
    const content = readFileSync(envPath, 'utf-8')
    const match = content.match(/^VITE_API_PORT=(.+)$/m)
    if (match) return match[1].trim()
  }
  return process.env.VITE_API_PORT || '5454'
}

const apiPort = getApiPort()

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': `http://127.0.0.1:${apiPort}`,
    },
  },
  build: {
    outDir: '../src/streamdoc/api/static',
    emptyOutDir: true,
  },
})
