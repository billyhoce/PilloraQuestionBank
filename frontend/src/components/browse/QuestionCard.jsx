export default function QuestionCard({ item, onClick }) {
  const { paper_info, topics, first_page_url, question_number } = item
  const uniqueTopicNames = [...new Set((topics || []).map(t => t.topic_name))]
  const subtopicNames = [...new Set((topics || []).map(t => t.subtopic_name))]
  const title = `${paper_info.school_name} ${paper_info.year} ${paper_info.exam_type_name} ${paper_info.paper_number} · Q${question_number}`

  return (
    <button
      type="button"
      onClick={onClick}
      className="group text-left bg-white border border-gray-200 rounded-lg overflow-hidden hover:border-blue-500 hover:shadow-md transition-all flex flex-col"
    >
      <div className="aspect-[3/4] bg-gray-100 overflow-hidden">
        {first_page_url ? (
          <img
            src={first_page_url}
            alt={title}
            loading="lazy"
            className="w-full h-full object-cover object-top"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-xs text-gray-400">No preview</div>
        )}
      </div>
      <div className="p-3 flex flex-col gap-1.5">
        {uniqueTopicNames.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {uniqueTopicNames.map(name => (
              <span
                key={name}
                className="text-[10px] px-1.5 py-0.5 border border-blue-300 text-blue-700 rounded bg-blue-50"
              >
                {name}
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
      </div>
    </button>
  )
}
