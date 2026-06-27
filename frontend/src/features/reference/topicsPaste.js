// Parses TSV copied from Google Sheets (columns: Topic No., Topic Name, Sub-Topic)
// into editable grid rows. Topic Name/No. cells are merged across a topic's subtopic
// rows, so a blank Topic Name means the row's subtopic belongs to the current topic.
// Some topics have no subtopics at all.

let keyCounter = 0
export function nextKey() {
  keyCounter += 1
  return `k${keyCounter}`
}

// Build empty grid rows (used for "add topic" / "add subtopic").
export function emptyTopicRow(topic_number) {
  return { key: nextKey(), id: null, topic_number, name: '', subtopics: [] }
}

export function emptySubtopicRow() {
  return { key: nextKey(), id: null, name: '' }
}

// Map the API topic list (TopicWithSubtopicsResponse[]) into grid rows.
export function topicsToRows(topics) {
  return (topics || []).map((t) => ({
    key: nextKey(),
    id: t.id,
    topic_number: t.topic_number,
    name: t.name,
    subtopics: (t.subtopics || []).map((s) => ({ key: nextKey(), id: s.id, name: s.name })),
  }))
}

// Parse pasted TSV into grid rows, carrying over ids from existing topics (matched by
// topic_number) and subtopics (matched by name within the topic) so a full-sync save
// keeps existing rows in place rather than recreating them.
export function parseTopicsTsv(text, existingTopics = []) {
  const existingByNumber = new Map()
  for (const t of existingTopics) existingByNumber.set(t.topic_number, t)

  const lines = String(text).replace(/\r\n?/g, '\n').split('\n')
  // Drop trailing blank lines.
  while (lines.length && lines[lines.length - 1].trim() === '') lines.pop()

  const rows = []
  const byName = new Map() // lowercased topic name -> row (collapses repeated names)
  let current = null
  let autoNumber = 0

  lines.forEach((line, index) => {
    const cells = line.split('\t')
    const noCell = (cells[0] ?? '').trim()
    const nameCell = (cells[1] ?? '').trim()
    const subCell = (cells[2] ?? '').trim()

    // Skip a header row.
    if (index === 0 && /topic\s*no/i.test(noCell)) return

    if (nameCell) {
      const nameKey = nameCell.toLowerCase()
      const existingRow = byName.get(nameKey)
      if (existingRow) {
        // Non-merged paste: the topic name is repeated on every subtopic row, so
        // keep adding to the same topic instead of creating a duplicate.
        current = existingRow
      } else {
        const parsedNo = parseInt(noCell, 10)
        autoNumber = Number.isFinite(parsedNo) && parsedNo > 0 ? parsedNo : autoNumber + 1
        const match = existingByNumber.get(autoNumber)
        current = {
          key: nextKey(),
          id: match ? match.id : null,
          topic_number: autoNumber,
          name: nameCell,
          subtopics: [],
        }
        byName.set(nameKey, current)
        rows.push(current)
      }
    }

    if (subCell && current) {
      const subKey = subCell.toLowerCase()
      const isDuplicate = current.subtopics.some((s) => s.name.trim().toLowerCase() === subKey)
      if (!isDuplicate) {
        const existTopic = existingByNumber.get(current.topic_number)
        const matchSub = existTopic
          ? (existTopic.subtopics || []).find((s) => s.name.trim().toLowerCase() === subKey)
          : undefined
        current.subtopics.push({ key: nextKey(), id: matchSub ? matchSub.id : null, name: subCell })
      }
    }
  })

  return rows
}
