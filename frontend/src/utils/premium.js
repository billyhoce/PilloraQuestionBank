// A question list-item is "locked" when its images are gated behind premium.
// The backend sets `locked` and withholds `first_page_url` for premium papers
// the viewer isn't entitled to; fall back to inferring it from the metadata.
export const isLocked = (item) =>
  item.locked ?? (item.paper_info?.is_premium && !item.first_page_url)
