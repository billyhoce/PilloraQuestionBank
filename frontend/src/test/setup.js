import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// RTL only auto-registers its cleanup when vitest globals are enabled; we use
// explicit imports, so unmount rendered trees between tests ourselves.
afterEach(cleanup)
