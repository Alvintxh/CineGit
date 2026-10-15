import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({ plugins: [react()], test: { environment: 'jsdom', maxWorkers: 2, include: ['tests/**/*.test.tsx'], setupFiles: ['./tests/setup.ts'], restoreMocks: true } })
