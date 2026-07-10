import { useState } from 'react'
import PageThumbnail from './PageThumbnail'
import Lightbox from './Lightbox'

function computeLabels(pages, dividerIdx) {
  const labels = new Array(pages.length)
  const qEnd = dividerIdx !== null ? dividerIdx : pages.length

  let qNum = 0
  for (let i = 0; i < qEnd; i++) {
    if (i === 0 || !pages[i].mergeWithPrev) qNum++
    labels[i] = `Q${qNum}`
  }

  if (dividerIdx !== null) {
    let aNum = 0
    for (let i = dividerIdx; i < pages.length; i++) {
      if (i === dividerIdx || !pages[i].mergeWithPrev) aNum++
      labels[i] = `A${aNum}`
    }
  }

  return labels
}

export default function PageGrid({ pages, dividerIdx, onToggleMerge, onSetDivider, onRemoveDivider }) {
  const [lightboxIdx, setLightboxIdx] = useState(null)
  const labels = computeLabels(pages, dividerIdx)

  return (
    <>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3 content-start overflow-y-auto max-h-[70vh] pb-4">
        {pages.map((page, i) => (
          <div className="relative group" key={page.temp_key}>
            <PageThumbnail
              page={page}
              label={labels[i]}
              canMerge={i > 0 && i !== dividerIdx}
              onToggleMerge={() => onToggleMerge(i)}
              onOpenLightbox={() => setLightboxIdx(i)}
            />
            {i === dividerIdx ? (
              <>
                <div className="absolute inset-y-0 -left-1.5 w-0 border-l-2 border-dashed border-red-400 pointer-events-none" />
                <button
                  type="button"
                  onClick={onRemoveDivider}
                  title="Remove divider"
                  className="absolute -left-2.5 top-1 text-red-500 hover:text-red-700 bg-white border border-red-300 rounded-full w-5 h-5 flex items-center justify-center text-xs leading-none"
                >
                  ×
                </button>
              </>
            ) : i >= 1 ? (
              <div
                className="absolute inset-y-0 -left-1.5 w-3 flex items-center justify-center cursor-pointer opacity-0 group-hover:opacity-100"
                onClick={() => onSetDivider(i)}
                title="Set Q/A divider here"
              >
                <span className="text-gray-400 text-sm select-none transition-opacity">÷</span>
              </div>
            ) : null}
          </div>
        ))}
      </div>
      <Lightbox
        pages={pages}
        currentIdx={lightboxIdx}
        onClose={() => setLightboxIdx(null)}
        onPrev={() => setLightboxIdx((idx) => Math.max(0, idx - 1))}
        onNext={() => setLightboxIdx((idx) => Math.min(pages.length - 1, idx + 1))}
        canMerge={(i) => i > 0 && i !== dividerIdx}
        onToggleMerge={onToggleMerge}
      />
    </>
  )
}
