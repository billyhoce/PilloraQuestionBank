export function buildTopicLookup(topics) {
  const subtopicById = new Map()
  const topicById = new Map()
  for (const t of topics || []) {
    topicById.set(t.id, t.name)
    for (const s of t.subtopics || []) {
      subtopicById.set(s.id, { name: s.name, topic_name: t.name })
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
