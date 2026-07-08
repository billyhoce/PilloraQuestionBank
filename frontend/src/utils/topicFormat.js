/**
 * Display convention for topics: always show the topic number as a "T{n}"
 * prefix, e.g. formatTopic(1, 'Algebra') -> "T1 Algebra".
 * Falls back to the bare name when no number is available.
 */
export function formatTopic(topicNumber, name) {
  if (topicNumber == null) return name
  return `T${topicNumber} ${name}`
}
