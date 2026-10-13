import { useEffect, useState } from 'react'
import { api } from '../../api/client'

export const emptyMetadata = {
  subject_id: null, stream_id: null, level_id: null,
  school_id: null, exam_type_id: null, year: '', paper_number: '',
  is_premium: true,  // imported papers are premium by default
}

// Fold AI/filename-suggested metadata (ids and numbers, any may be null) into the sidebar's state.
export function mergeSuggested(prev, s) {
  return {
    ...prev,
    ...(s.subject_id != null && { subject_id: s.subject_id }),
    ...(s.stream_id != null && { stream_id: s.stream_id }),
    ...(s.level_id != null && { level_id: s.level_id }),
    ...(s.school_id != null && { school_id: s.school_id }),
    ...(s.exam_type_id != null && { exam_type_id: s.exam_type_id }),
    ...(s.year != null && { year: String(s.year) }),
    ...(s.paper_number != null && { paper_number: String(s.paper_number) }),
  }
}

// The reference lists the metadata sidebar offers (null until loaded).
export function useReferenceData() {
  const [refs, setRefs] = useState(null)
  useEffect(() => {
    Promise.all([
      api.subjects.list(),
      api.streams.list(),
      api.levels.list(),
      api.schools.list(),
      api.examTypes.list(),
      api.schoolLevels.list(),
    ]).then(([subjects, streams, levels, schools, examTypes, schoolLevels]) => {
      const slMap = Object.fromEntries(schoolLevels.map(sl => [sl.id, sl.name]))
      const namedLevels = levels.map(l => ({
        ...l,
        name: slMap[l.school_level_id] ? `${slMap[l.school_level_id]} ${l.name}` : l.name,
      }))
      setRefs({ subjects, streams, levels: namedLevels, schools, examTypes })
    })
  }, [])
  return refs
}
