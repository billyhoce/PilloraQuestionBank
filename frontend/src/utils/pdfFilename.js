/**
 * Descriptive filenames for generated PDFs.
 *
 * Format: `Pillora_<Level>_<Stream>_<Subject>_<TopicInfo>_<PDFType>.pdf`
 * where <PDFType> is `Paper` (combined), `Questions`, or `Answers`.
 *
 * Topic portion:
 *   - 1 topic      → code + hyphenated name, e.g. `T1-Algebra`
 *   - 2–5 topics   → codes only, e.g. `T1_T23_T28`
 *   - >5 or none   → omitted
 *
 * When no structured filter (Level/Stream/Subject/Topics) is active — i.e. the
 * user is browsing with defaults and/or the search bar only — the name falls
 * back to a dated form, e.g. `Pillora_2026-07-14_Paper.pdf`.
 */

const PDF_TYPE_LABEL = {
  combined: 'Paper',
  question: 'Questions',
  answer: 'Answers',
}

// Drop characters that are invalid in filenames, then map remaining whitespace.
function sanitize(value, spacesTo = '') {
  return String(value ?? '')
    .replace(/[\\/:*?"<>|]/g, '')
    .trim()
    .replace(/\s+/g, spacesTo)
}

// Current date as YYYY-MM-DD.
function formatDate(d) {
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

// Build the <TopicInfo> segment from the selected topics (empty string = omit).
function topicPart(topics) {
  const list = [...(topics || [])]
    .filter((t) => t && t.topic_number != null)
    .sort((a, b) => a.topic_number - b.topic_number)

  if (list.length === 0 || list.length > 5) return ''

  if (list.length === 1) {
    const t = list[0]
    const name = sanitize(t.name, '-')
    return name ? `T${t.topic_number}-${name}` : `T${t.topic_number}`
  }

  return list.map((t) => `T${t.topic_number}`).join('_')
}

/**
 * Build a download filename for a generated PDF.
 *
 * @param {Object} params
 * @param {'combined'|'question'|'answer'} params.variant - which PDF this is.
 * @param {Object} [params.context] - active filter context:
 *   { level, stream, subject } as display names (or falsy when unset) and
 *   { topics } as an array of selected `{ topic_number, name }` objects.
 * @param {Date} [params.now] - reference date for the dated fallback.
 * @returns {string} filename ending in `.pdf`.
 */
export function buildPdfFilename({ variant, context = {}, now = new Date() }) {
  const type = PDF_TYPE_LABEL[variant] || 'Paper'
  const { level, stream, subject, topics } = context

  const segments = []
  if (level) segments.push(sanitize(level))
  if (stream) segments.push(sanitize(stream))
  if (subject) segments.push(sanitize(subject))
  const tp = topicPart(topics)
  if (tp) segments.push(tp)

  if (segments.length === 0) {
    return `Pillora_${formatDate(now)}_${type}.pdf`
  }
  return `Pillora_${segments.join('_')}_${type}.pdf`
}
