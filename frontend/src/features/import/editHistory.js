// Undo/redo for the review page's box editor: the papers before each edit, newest last, kept to
// the last UNDO_LIMIT edits. A `gesture` (a drag, a run of arrow-key nudges) records only its first
// edit, so one drag or one run of nudges is undone in one step.

export const UNDO_LIMIT = 10

export const emptyHistory = { past: [], future: [], gesture: null }

// After an edit from `before`: remember it, unless it continues the gesture already recorded. A new
// edit drops whatever could have been redone.
export function record(history, before, gesture = null) {
  if (gesture != null && gesture === history.gesture) return history
  return { past: [...history.past, before].slice(-UNDO_LIMIT), future: [], gesture }
}

// The next edit starts a fresh undo step even if it is the same kind of gesture.
export function breakGesture(history) {
  return history.gesture == null ? history : { ...history, gesture: null }
}

// Step back from `current`: { history, paper } with the paper to show, or null when nothing is left.
export function undo(history, current) {
  if (!history.past.length) return null
  return {
    paper: history.past[history.past.length - 1],
    history: { past: history.past.slice(0, -1), future: [current, ...history.future], gesture: null },
  }
}

// Step forward again after an undo, or null when there is nothing to redo.
export function redo(history, current) {
  if (!history.future.length) return null
  return {
    paper: history.future[0],
    history: { past: [...history.past, current].slice(-UNDO_LIMIT), future: history.future.slice(1), gesture: null },
  }
}
