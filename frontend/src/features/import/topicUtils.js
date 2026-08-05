export function buildTopicLookup(topics) {
  const subtopicById = new Map()
  const topicById = new Map()
  for (const t of topics || []) {
    topicById.set(t.id, { name: t.name, topic_number: t.topic_number })
    for (const s of t.subtopics || []) {
      subtopicById.set(s.id, { name: s.name, topic_name: t.name, topic_number: t.topic_number })
    }
  }
  return { subtopicById, topicById }
}

export function selectionsToAssignments(selections) {
  const byTopicId = new Map()
  for (const sel of selections) {
    if (!byTopicId.has(sel.topic_id)) byTopicId.set(sel.topic_id, [])
    if (sel.subtopic_id != null) byTopicId.get(sel.topic_id).push({ subtopic_id: sel.subtopic_id })
  }
  return [...byTopicId.entries()].map(([topic_id, subtopics]) => ({ topic_id, subtopics }))
}

/** A blank part. Every question has at least one, so this seeds new questions
 *  and questions the AI returned nothing for. */
export function emptyPart() {
  return { label: '', marks: null, selected: [] }
}

/** Normalize parts from any API shape ({label, marks, selections}) into the
 *  editor's working shape. Always returns at least one part. */
export function partsFromApi(parts) {
  const out = (parts || []).map((p) => ({
    label: p.label ?? '',
    marks: p.marks ?? null,
    selected: p.selections || [],
  }))
  return out.length > 0 ? out : [emptyPart()]
}

/** Editor shape -> the `parts` array the save endpoints expect. */
export function partsToPayload(parts) {
  return (parts || []).map((p) => ({
    label: p.label ?? '',
    marks: p.marks ?? null,
    topic_assignments: selectionsToAssignments(p.selected || []),
  }))
}

/** Sum of the parts' marks, or null when no part carries any — matches the
 *  backend's SUM semantics so the editor total agrees with what gets saved. */
export function partsTotalMarks(parts) {
  const marked = (parts || []).filter((p) => p.marks != null)
  if (marked.length === 0) return null
  return marked.reduce((sum, p) => sum + Number(p.marks), 0)
}
