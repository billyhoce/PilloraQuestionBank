import { Link } from 'react-router-dom'
import premiumLocked from '../../assets/premium-locked.svg'
import { formatTopic } from '../../utils/topicFormat'

export default function QuestionCard({ item, onClick, selectable = false, selected = false, onToggleSelect }) {
  const { paper_info, topics, tags, first_page_url, question_number, marks } = item
  // The backend withholds the image URL for premium papers when the viewer isn't
  // entitled and sets `locked`. Fall back to inferring it from the metadata.
  const locked = item.locked ?? (paper_info.is_premium && !first_page_url)
  const uniqueTopics = [...new Map((topics || []).map(t => [t.topic_name, t])).values()]
  const subtopicNames = [...new Set((topics || []).flatMap(t => t.subtopic_names || []))]
  const questionTags = tags || []
  const title = `${paper_info.school_name} ${paper_info.year} ${paper_info.exam_type_name} ${paper_info.paper_number} · Q${question_number}`

  const preview = (
    <div className="aspect-[5/2] bg-white overflow-hidden">
      {locked ? (
        <img
          src={premiumLocked}
          alt="Premium content — subscribe to unlock"
          className="w-full h-full object-contain"
        />
      ) : first_page_url ? (
        <img
          src={first_page_url}
          alt={title}
          loading="lazy"
          className="block w-full h-auto"
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-xs text-gray-400">No preview</div>
      )}
    </div>
  )

  const meta = (
    <>
      {uniqueTopics.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {uniqueTopics.map(t => (
            <span
              key={t.topic_name}
              className="text-[10px] px-1.5 py-0.5 border border-blue-300 text-blue-700 rounded bg-blue-50"
            >
              {formatTopic(t.topic_number, t.topic_name)}
            </span>
          ))}
        </div>
      ) : null}
      <div className="text-sm font-semibold text-gray-900 leading-snug">{title}</div>
      {subtopicNames.length > 0 ? (
        <div className="text-xs text-gray-500 leading-snug line-clamp-2">
          {subtopicNames.join(', ')}
        </div>
      ) : null}
      {questionTags.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {questionTags.map(t => (
            <span
              key={t.id}
              className="text-[10px] px-1.5 py-0.5 border border-amber-300 text-amber-800 rounded-full bg-amber-50"
            >
              {t.name}
            </span>
          ))}
        </div>
      ) : null}
    </>
  )

  // Selection mode (Paper Generation): card is not a single button, so we can
  // nest a preview button and an Add/Added button without invalid markup.
  if (selectable) {
    return (
      <div
        className={`bg-white border-2 rounded-lg overflow-hidden flex flex-col transition-all ${
          selected ? 'border-blue-500 shadow-md' : 'border-gray-300 hover:border-blue-400'
        }`}
      >
        <button type="button" onClick={onClick} className="block text-left w-full">
          {preview}
        </button>
        <div className="p-3 flex flex-col gap-1.5">
          {meta}
          <div className="flex items-center justify-between pt-1">
            <span className="text-xs text-gray-600">
              {marks != null ? `${marks} ${marks === 1 ? 'mark' : 'marks'}` : 'Marks —'}
            </span>
            {locked ? (
              <Link
                to="/subscribe"
                className="text-xs font-medium px-2.5 py-1 rounded border border-amber-400 text-amber-800 bg-amber-50 hover:bg-amber-100 transition-colors"
              >
                🔒 Subscribe
              </Link>
            ) : (
              <button
                type="button"
                onClick={onToggleSelect}
                className={`text-xs font-medium px-2.5 py-1 rounded transition-colors ${
                  selected
                    ? 'bg-blue-600 text-white hover:bg-blue-700'
                    : 'border border-blue-500 text-blue-600 hover:bg-blue-50'
                }`}
              >
                {selected ? '✓ Added' : '+ Add'}
              </button>
            )}
          </div>
        </div>
      </div>
    )
  }

  // Default (Browse): the whole card is a single clickable button.
  return (
    <button
      type="button"
      onClick={onClick}
      className="group text-left bg-white border-2 border-gray-300 rounded-lg overflow-hidden hover:border-blue-500 hover:shadow-md transition-all flex flex-col"
    >
      {preview}
      <div className="p-3 flex flex-col gap-1.5">{meta}</div>
    </button>
  )
}
