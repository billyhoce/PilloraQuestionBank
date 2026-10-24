// Character bigrams of a name, lower-cased, with their counts.
function bigrams(s) {
  const t = ` ${s.toLowerCase().replace(/\s+/g, ' ').trim()} `
  const out = new Map()
  for (let i = 0; i < t.length - 1; i++) {
    const g = t.slice(i, i + 2)
    out.set(g, (out.get(g) ?? 0) + 1)
  }
  return out
}

// How alike two names are, 0..1 (Dice coefficient over character bigrams).
function likeness(a, b) {
  const x = bigrams(a)
  const y = bigrams(b)
  let shared = 0
  let total = 0
  for (const [g, n] of x) { shared += Math.min(n, y.get(g) ?? 0); total += n }
  for (const n of y.values()) total += n
  return total ? (2 * shared) / total : 0
}

// Every school, the ones whose name is closest to `name` first (a stable sort: ties keep their order).
export function closestSchools(name, schools) {
  return schools
    .map((s, i) => ({ s, i, score: likeness(name, s.name) }))
    .sort((a, b) => b.score - a.score || a.i - b.i)
    .map(x => x.s)
}
