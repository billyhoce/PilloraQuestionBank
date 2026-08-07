// A question list-item is "locked" when its images are gated behind premium.
// The backend sets `locked` and withholds `first_page_url` for premium papers
// the viewer isn't entitled to; fall back to inferring it from the metadata.
export const isLocked = (item) =>
  item.locked ?? (item.paper_info?.is_premium && !item.first_page_url)

// Premium is sold per school level, so a locked item names the group the viewer
// is missing — "Secondary", not just "premium". Level names alone can't say it:
// "1" is both Primary 1 and Secondary 1.
export const requiredSchoolLevel = (item) => item?.paper_info?.school_level_name || null

// Where a locked item's Subscribe CTA points. The query param lets the Subscribe
// page highlight the plan the viewer actually needs.
export const subscribeHref = (item) => {
  const level = requiredSchoolLevel(item)
  return level ? `/subscribe?school_level=${encodeURIComponent(level)}` : '/subscribe'
}

// Does this user hold premium for `schoolLevelName`? Admins hold everything.
export const hasSchoolLevel = (user, schoolLevelName) =>
  user?.role === 'admin' ||
  (user?.premium_school_levels || []).some((sl) => sl.name === schoolLevelName)
