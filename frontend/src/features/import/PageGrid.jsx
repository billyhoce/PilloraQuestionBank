import React, { useState } from 'react'
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

function DividerZone({ active, onSet, onRemove }) {
  if (active) {
    return (
      <div className="flex flex-col items-center justify-center w-8 flex-shrink-0 self-stretch gap-1 py-2">
        <div className="flex-1 w-0 border-l-2 border-dashed border-red-400" />
        <button
          type="button"
          onClick={onRemove}
          title="Remove divider"
          className="text-red-500 hover:text-red-700 bg-white border border-red-300 rounded-full w-5 h-5 flex items-center justify-center text-xs leading-none flex-shrink-0"
        >
          ×
        </button>
        <div className="flex-1 w-0 border-l-2 border-dashed border-red-400" />
      </div>
    )
  }
  return (
    <div
      className="group flex flex-col items-center justify-center w-5 flex-shrink-0 self-stretch cursor-pointer"
      onClick={onSet}
      title="Set Q/A divider here"
    >
      <span className="opacity-0 group-hover:opacity-100 text-gray-400 text-sm select-none transition-opacity">
        ÷
      </span>
    </div>
  )
}

export default function PageGrid({ pages, dividerIdx, onToggleMerge, onSetDivider, onRemoveDivider }) {
  const [lightboxIdx, setLightboxIdx] = useState(null)
  const labels = computeLabels(pages, dividerIdx)

  return (
    <>
      <div className="flex flex-row overflow-x-auto pb-4 items-start">
        {pages.map((page, i) => (
          <React.Fragment key={page.temp_key}>
            <PageThumbnail
              page={page}
              label={labels[i]}
              canMerge={i > 0 && i !== dividerIdx}
              onToggleMerge={() => onToggleMerge(i)}
              onOpenLightbox={() => setLightboxIdx(i)}
            />
            {i < pages.length - 1 && (
              <DividerZone
                active={dividerIdx === i + 1}
                onSet={() => onSetDivider(i + 1)}
                onRemove={onRemoveDivider}
              />
            )}
          </React.Fragment>
        ))}
      </div>
      <Lightbox
        pages={pages}
        currentIdx={lightboxIdx}
        onClose={() => setLightboxIdx(null)}
        onPrev={() => setLightboxIdx((idx) => Math.max(0, idx - 1))}
        onNext={() => setLightboxIdx((idx) => Math.min(pages.length - 1, idx + 1))}
      />
    </>
  )
}
