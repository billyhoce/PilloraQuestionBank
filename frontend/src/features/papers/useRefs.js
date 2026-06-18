import { useEffect, useState } from 'react'
import { api } from '../../api/client'

// Loads the reference data needed for paper metadata selects. Mirrors the
// loading logic in the import flow's ImportPage, including composing level
// names with their school level (e.g. "secondary Sec 1").
export default function useRefs() {
  const [refs, setRefs] = useState(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      api.subjects.list(),
      api.streams.list(),
      api.levels.list(),
      api.schools.list(),
      api.examTypes.list(),
      api.schoolLevels.list(),
    ]).then(([subjects, streams, levels, schools, examTypes, schoolLevels]) => {
      if (cancelled) return
      const slMap = Object.fromEntries(schoolLevels.map((sl) => [sl.id, sl.name]))
      const namedLevels = levels.map((l) => ({
        ...l,
        name: slMap[l.school_level_id] ? `${slMap[l.school_level_id]} ${l.name}` : l.name,
      }))
      setRefs({ subjects, streams, levels: namedLevels, schools, examTypes })
    })
    return () => { cancelled = true }
  }, [])

  return refs
}
