import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api } from '../api/client'

// The two site-wide settings, fetched once for the whole app. Both the About
// page and every question image need them, so a per-page fetch (the pattern
// /api/generation-config still uses) would mean several identical requests per
// navigation. `GET /api/site-config` is public, so this runs signed-out too.
const SiteConfigContext = createContext(null)

const EMPTY = { about_content: '', protect_images: false }

export function SiteConfigProvider({ children }) {
  const [config, setConfig] = useState(EMPTY)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(
    () =>
      api.siteConfig
        .get()
        .then((cfg) => {
          setConfig(cfg || EMPTY)
          return cfg
        })
        // A failed fetch must not blank the page: fall back to protection off
        // and empty copy, which is what an unseeded database would return.
        .catch(() => setConfig(EMPTY))
        .finally(() => setLoading(false)),
    [],
  )

  useEffect(() => { refresh() }, [refresh])

  return (
    <SiteConfigContext.Provider
      value={{
        aboutContent: config.about_content || '',
        protectImages: !!config.protect_images,
        loading,
        setConfig,
        refresh,
      }}
    >
      {children}
    </SiteConfigContext.Provider>
  )
}

// Returns safe defaults when no provider is mounted, so a component under test
// (or rendered outside the shell) doesn't have to stub the context.
export function useSiteConfig() {
  return useContext(SiteConfigContext) ?? {
    aboutContent: '',
    protectImages: false,
    loading: false,
    setConfig: () => {},
    refresh: () => Promise.resolve(),
  }
}
