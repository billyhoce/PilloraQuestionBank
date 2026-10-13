import { useAuth } from '../context/AuthContext'
import { useSiteConfig } from '../context/SiteConfigContext'

// A question image with an optional client-side copy deterrent, controlled by
// the site-wide `protect_images` toggle (User Management → Site Settings).
//
// **This is a deterrent, not protection.** Images reach the browser as presigned
// S3 URLs embedded in the JSON response, so anyone who opens the Network tab can
// still fetch the file. What it does stop is the way casual copying actually
// happens: right-click → Save Image, drag-to-desktop, and the iOS long-press
// sheet. Raising that bar is the whole goal; do not add server-side complexity
// on the assumption that this is airtight.
//
// Admins always get a plain <img> — they need to save and inspect images while
// importing and editing papers.
export default function ProtectedImage({ className, style, ...imgProps }) {
  // Both contexts are read defensively: this is a leaf that renders inside
  // cards which tests mount without any provider, and a missing provider should
  // mean "no protection", not a crash.
  const { user } = useAuth() ?? {}
  const { protectImages } = useSiteConfig()

  if (!protectImages || user?.role === 'admin') {
    return <img className={className} style={style} {...imgProps} />
  }

  return (
    // The wrapper carries the context-menu handler so the overlay, the image and
    // the padding between them all suppress it. `contents`-free `block` wrapper
    // keeps the layout identical to the bare <img> it replaces.
    <span
      className="relative block"
      onContextMenu={e => e.preventDefault()}
      onDragStart={e => e.preventDefault()}
    >
      {/* .protected-image (index.css) turns off selection and the iOS
          long-press "Save Image" sheet. */}
      <img
        className={`protected-image${className ? ` ${className}` : ''}`}
        draggable={false}
        style={style}
        {...imgProps}
      />
      {/* Transparent layer in front of the image, so a right-click or long-press
          targets an empty element rather than the picture. Deliberately an empty
          span rather than a transparent PNG: it behaves the same for the events
          that matter and costs no extra request. `pointer-events: none` is NOT
          used — the overlay must receive the events — and because it sits inside
          whatever button wraps it (see QuestionCard), plain clicks still bubble
          up to the card's own onClick. */}
      <span aria-hidden="true" className="absolute inset-0" />
    </span>
  )
}
