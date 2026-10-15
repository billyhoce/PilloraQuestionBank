// The ingest pipeline's stages (ingestion/pipeline/registry.py) grouped into the few steps an
// admin cares about. A job reports only its current `stage` (the running task's, else the most
// recently finished one's) and a task count; this turns that into "which step, how far".

export const PHASES = [
  { id: 'upload', label: 'Upload', stages: [] },
  { id: 'read', label: 'Read PDF', stages: ['register'] },
  { id: 'find', label: 'Find papers', stages: ['segment'] },
  { id: 'split', label: 'Split', stages: ['split'] },
  // Per-section stages: the question route (locate → render) and the answer-table route
  // (grid → ocr → questions → render).
  { id: 'extract', label: 'Extract questions', stages: ['locate', 'render', 'grid', 'ocr', 'questions'] },
  { id: 'assemble', label: 'Assemble', stages: ['report'] },
]

const READY = PHASES.length // past the last step: ready for review

export function phaseIndexOfStage(stage) {
  const i = PHASES.findIndex(p => p.stages.includes(stage))
  return i < 0 ? null : i
}

// Where a job is: { current, state } — `current` is the index of the step in hand (PHASES.length
// once there is nothing left to run), `state` is 'active' | 'waiting' | 'failed' | 'done'.
// `upload` (0..1) is a browser-side transfer that has no server job yet, or whose job is still
// `awaiting_upload`.
export function jobPhase(job) {
  switch (job.status) {
    case 'awaiting_upload':
      return { current: 0, state: 'active' }
    case 'queued':
      // Uploaded, nothing started: waiting for the worker to pick up "Read PDF".
      return { current: Math.max(1, phaseIndexOfStage(job.stage) ?? 1), state: 'waiting' }
    case 'running':
      return { current: phaseIndexOfStage(job.stage) ?? 1, state: 'active' }
    case 'failed':
      return { current: phaseIndexOfStage(job.stage) ?? failedPhaseFromError(job.error) ?? 1, state: 'failed' }
    default:
      // review_ready, confirmed, cancelled, expired: the pipeline is behind it.
      return { current: READY, state: 'done' }
  }
}

// A job-level failure names its stage first: "register failed: The PDF is password protected".
function failedPhaseFromError(error) {
  const m = /^(\w+) failed/.exec(error || '')
  return m ? phaseIndexOfStage(m[1]) : null
}

// A short line for the step in hand: "Extract questions · 5/9 tasks".
export function phaseCaption(job) {
  const { current, state } = jobPhase(job)
  if (state === 'done') return 'Done'
  const label = PHASES[current]?.label ?? ''
  if (state === 'waiting') return 'Waiting for the worker'
  const tasks = job.tasks_total > 0 ? ` · ${job.tasks_done}/${job.tasks_total} tasks` : ''
  return state === 'failed' ? `Failed at ${label}` : `${label}${tasks}`
}
