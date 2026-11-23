import { rectToPx } from './reviewGeometry'

// The part of a review page image inside `rect` (PDF points), scaled to fit its box.
export default function RectPreview({ url, page, rect, alt }) {
  const box = rectToPx(rect, page)
  return (
    <div className="relative overflow-hidden border border-gray-300 bg-white" style={{ aspectRatio: `${box.width} / ${box.height}` }}>
      <img
        src={url}
        alt={alt}
        className="absolute max-w-none"
        style={{
          width: `${(page.width_px / box.width) * 100}%`,
          left: `${(-box.x / box.width) * 100}%`,
          top: `${(-box.y / box.height) * 100}%`,
        }}
      />
    </div>
  )
}

// A preview from the server or the review: a page crop when it has a rectangle, else a whole
// (bank) question image.
export function Thumbnail({ preview, alt }) {
  if (!preview?.url) return <p className="text-xs text-gray-500">No image.</p>
  if (preview.rect && preview.page) return <RectPreview url={preview.url} page={preview.page} rect={preview.rect} alt={alt} />
  return <img src={preview.url} alt={alt} className="w-full border border-gray-300" />
}
