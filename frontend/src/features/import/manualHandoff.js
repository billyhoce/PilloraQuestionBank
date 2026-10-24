// Hand a page range of an auto-import job's source PDF to the Manual import flow: the manual
// wizard restores its state from sessionStorage, so we write the session it would have written
// after its own PDF upload (step "review", the pages, the suggested metadata).

import { emptyMetadata, mergeSuggested } from './importMetadata'

export const MANUAL_SESSION_KEY = 'pillora_import_session'

// `result` is what POST /api/import/jobs/{id}/manual-pages returns ({ pages, suggested_metadata }).
export function manualSessionFrom(result) {
  const s = result.suggested_metadata || {}
  const metadata = mergeSuggested(emptyMetadata, s)
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
