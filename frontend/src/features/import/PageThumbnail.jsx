export default function PageThumbnail({ page, label, canMerge, onToggleMerge, onOpenLightbox }) {
  return (
    <div
      className={`flex-shrink-0 w-44 flex flex-col rounded border-2 bg-white overflow-hidden ${
        page.mergeWithPrev ? 'border-blue-400' : 'border-gray-200'
      }`}
    >
      <button
        type="button"
        onClick={onOpenLightbox}
        className="relative w-full focus:outline-none"
      >
        <img
          src={page.url}
          alt={label}
          className="w-full object-contain bg-gray-100"
          style={{ height: '220px' }}
        />
      </button>
      <div className="px-2 py-1.5 flex items-center justify-between bg-gray-50 border-t border-gray-200">
        <span className="text-xs font-semibold text-gray-700">{label}</span>
        {canMerge && (
          <button
            type="button"
            title="Merge with previous"
            onClick={onToggleMerge}
            className={`text-xs px-1.5 py-0.5 rounded border transition-colors ${
              page.mergeWithPrev
                ? 'bg-blue-100 text-blue-700 border-blue-300'
                : 'text-gray-400 border-gray-200 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            merge
          </button>
        )}
      </div>
    </div>
  )
}
