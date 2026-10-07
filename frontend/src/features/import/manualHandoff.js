// Hand a page range of an auto-import job's source PDF to the Manual import flow: the manual
// wizard restores its state from sessionStorage, so we write the session it would have written
// after its own PDF upload (step "review", the pages, the suggested metadata).

export const MANUAL_SESSION_KEY = 'pillora_import_session'

const EMPTY_METADATA = {
  subject_id: null, stream_id: null, level_id: null,
  school_id: null, exam_type_id: null, year: '', paper_number: '',
  is_premium: true,
}

// `result` is what POST /api/import/jobs/{id}/manual-pages returns ({ pages, suggested_metadata }).
export function manualSessionFrom(result) {
  const s = result.suggested_metadata || {}
  const metadata = { ...EMPTY_METADATA }
  for (const k of ['subject_id', 'stream_id', 'level_id', 'school_id', 'exam_type_id']) {
    if (s[k] != null) metadata[k] = s[k]
  }
  if (s.year != null) metadata.year = String(s.year)
  if (s.paper_number != null) metadata.paper_number = String(s.paper_number)
  return {
    step: 'review',
    pages: result.pages.map(p => ({ ...p, mergeWithPrev: false })),
    dividerIdx: null,
    metadata,
    paperId: null,
    confirmedQuestions: [],
  }
}

export function startManualImport(result) {
  sessionStorage.setItem(MANUAL_SESSION_KEY, JSON.stringify(manualSessionFrom(result)))
}
