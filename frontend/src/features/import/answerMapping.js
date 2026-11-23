// The answer mapping table (#92): which answers of an answer-only paper go onto which questions
// of the paper they are paired or attached with. A mapping is { answer label: question label or
// null } (null: left off); the server places an answer it does not name by its number.
//   questions - [{ label, answered }] (`answered`: the question has answers of its own)
//   answers   - [{ label }]
import { questionList } from './answerCoverage'

const asNumber = label => {
  const v = Number(String(label).trim())
  return String(label).trim() !== '' && Number.isInteger(v) ? v : null
}

// Each answer onto the question with its number plus `shift` (a Section B restarting at 1 needs
// +10, say), else onto nothing. A label that is not a plain number ("3a") only matches the same
// label, unshifted.
export function byNumber(questions, answers, shift = 0) {
  const labels = new Set(questions.map(q => q.label))
  const out = {}
  for (const a of answers) {
    const n = asNumber(a.label)
    const target = n == null ? (shift === 0 ? a.label : null) : String(n + shift)
    out[a.label] = labels.has(target) ? target : null
  }
  return out
}

// The table's first rows: by number, overridden by a pair's stored mapping where it names an answer.
export function startMapping(questions, answers, stored) {
  const out = byNumber(questions, answers)
  for (const a of answers) if (stored && a.label in stored) out[a.label] = stored[a.label]
  return out
}

export const moveAnswer = (mapping, answer, question) => ({ ...mapping, [answer]: question })

export const answersOn = (mapping, answers, question) => answers.filter(a => mapping[a.label] === question)

// "Q11–Q12 would get no answers" and "Answer 13 has no question": warnings only, never a stop.
export function mappingWarnings(mapping, questions) {
  const labels = new Set(questions.map(q => q.label))
  const placed = new Set(Object.values(mapping))
  const bare = questions.filter(q => !q.answered && !placed.has(q.label)).map(q => q.label)
  const lost = Object.keys(mapping).filter(a => !labels.has(mapping[a]))
  const out = []
  if (bare.length) out.push(`${questionList(bare)} would get no answers`)
  if (lost.length === 1) out.push(`Answer ${lost[0]} has no question`)
  if (lost.length > 1) out.push(`Answers ${lost.join(', ')} have no question`)
  return out
}
