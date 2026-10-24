import { Link, Outlet, useLocation } from 'react-router-dom'
import useReviewQueue from './useReviewQueue'
import { useUploadQueue } from './uploadQueueContext'

function Badge({ n, tone, label }) {
  if (!n) return null
  const cls = tone === 'blue' ? 'bg-blue-600 text-white' : 'bg-gray-200 text-gray-700'
  return <span aria-label={label} className={`ml-1.5 inline-block min-w-5 rounded-full px-1.5 text-xs leading-5 ${cls}`}>{n}</span>
}

// The import area: Auto import (drop PDFs, watch them process), Review queue (finished jobs
// waiting for a decision) and Manual import, as three pages under one sub-navigation. The review
// queue is polled here once and handed to the pages through the outlet context.
export default function ImportLayout() {
  const reviewQueue = useReviewQueue()
  const uploads = useUploadQueue()
  const { pathname } = useLocation()
  const uploading = uploads?.items.filter(it => it.status !== 'failed').length ?? 0
  const toReview = reviewQueue.jobs?.length ?? 0

  const tabs = [
    { to: '/admin/import/auto', label: 'Auto import', badge: <Badge n={uploading} label={`${uploading} uploading`} /> },
    {
      to: '/admin/import/review',
      label: 'Review queue',
      badge: <Badge n={toReview} tone="blue" label={`${toReview} ready for review`} />,
      // A job's own review page belongs to the queue.
      also: '/admin/import/jobs/',
    },
    { to: '/admin/import/manual', label: 'Manual import' },
  ]

  return (
    <div>
      <nav aria-label="Import" className="flex gap-1 px-4 pt-3 border-b border-gray-200 bg-white">
        {tabs.map(t => {
          const active = pathname === t.to || pathname.startsWith(`${t.to}/`) || (t.also && pathname.startsWith(t.also))
          return (
            <Link
              key={t.to}
              to={t.to}
              aria-current={active ? 'page' : undefined}
              className={`px-4 py-2 text-sm font-medium -mb-px border-b-2 ${
                active ? 'border-blue-600 text-blue-700' : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              {t.label}
              {t.badge}
            </Link>
          )
        })}
      </nav>
      <Outlet context={{ reviewQueue }} />
    </div>
  )
}
