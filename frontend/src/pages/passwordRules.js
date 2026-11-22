// Mirrors _PASSWORD_RULES in app/schemas/auth.py — change both. The server is the guard; this copy
// exists so the register page can say which rule a password breaks instead of a generic 422.
export const PASSWORD_RULES = [
  { test: (p) => p.length >= 8, label: 'At least 8 characters' },
  { test: (p) => /[A-Z]/.test(p), label: 'An uppercase letter' },
  { test: (p) => /[a-z]/.test(p), label: 'A lowercase letter' },
  { test: (p) => /[0-9]/.test(p), label: 'A number' },
  { test: (p) => /[^A-Za-z0-9]/.test(p), label: 'A special character' },
]

// The labels of the rules `password` fails, in rule order.
export function passwordFailures(password) {
  return PASSWORD_RULES.filter((r) => !r.test(password)).map((r) => r.label)
}
