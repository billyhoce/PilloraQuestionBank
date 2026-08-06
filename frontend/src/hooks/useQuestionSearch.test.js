import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'

import { api } from '../api/client'
import { filtersToListArgs, useQuestionSearch, PAGE_SIZE } from './useQuestionSearch'

const FILTERS = {
  subject_id: '3',
  stream_id: '',
  level_id: '',
  school_id: '',
  exam_type_id: '',
  year: '',
  paper_number: '',
  topic_ids: [7],
  exclusive: true,
  search: 'algebra',
}

beforeEach(() => {
  vi.spyOn(api.questions, 'list')
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('filtersToListArgs', () => {
  it('drops empty strings so they never reach the query string', () => {
    const args = filtersToListArgs(FILTERS, 1)
    expect(args.subject_id).toBe('3')
    expect(args.stream_id).toBeUndefined()
    expect(args.year).toBeUndefined()
  })

  it('passes topic selection and paging through', () => {
    const args = filtersToListArgs(FILTERS, 2)
    expect(args.topic_ids).toEqual([7])
    expect(args.exclusive).toBe(true)
    expect(args.page).toBe(2)
    expect(args.page_size).toBe(PAGE_SIZE)
  })
})

describe('useQuestionSearch', () => {
  it('fetches page 1 on mount and exposes the results', async () => {
    api.questions.list.mockResolvedValue({ items: [{ id: 1 }, { id: 2 }], total: 2 })

    const { result } = renderHook(() => useQuestionSearch(FILTERS))

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.items.map(i => i.id)).toEqual([1, 2])
    expect(result.current.total).toBe(2)
    expect(result.current.error).toBeNull()
  })

  it('appends the next page and de-dupes ids already held', async () => {
    api.questions.list
      .mockResolvedValueOnce({ items: [{ id: 1 }, { id: 2 }], total: 4 })
      .mockResolvedValueOnce({ items: [{ id: 2 }, { id: 3 }], total: 4 })

    const { result } = renderHook(() => useQuestionSearch(FILTERS))
    await waitFor(() => expect(result.current.loading).toBe(false))

    await act(async () => { await result.current.loadMore() })

    // id 2 came back on both pages but appears once.
    expect(result.current.items.map(i => i.id)).toEqual([1, 2, 3])
    expect(result.current.page).toBe(2)
  })

  it('refetches from page 1 when the filters change by value', async () => {
    api.questions.list.mockResolvedValue({ items: [{ id: 1 }], total: 1 })

    const { result, rerender } = renderHook(({ f }) => useQuestionSearch(f), {
      initialProps: { f: FILTERS },
    })
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(api.questions.list).toHaveBeenCalledTimes(1)

    // A new object with identical contents must NOT refetch — the hook keys on
    // the filter values, not object identity, or every render would refetch.
    rerender({ f: { ...FILTERS } })
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(api.questions.list).toHaveBeenCalledTimes(1)

    rerender({ f: { ...FILTERS, search: 'geometry' } })
    await waitFor(() => expect(api.questions.list).toHaveBeenCalledTimes(2))
    expect(api.questions.list.mock.calls[1][0].search).toBe('geometry')
  })

  it('surfaces a fetch failure as an error message', async () => {
    api.questions.list.mockRejectedValue({ message: 'Server error.' })

    const { result } = renderHook(() => useQuestionSearch(FILTERS))

    await waitFor(() => expect(result.current.error).toBe('Server error.'))
    expect(result.current.items).toEqual([])
  })

  it('ignores an aborted request rather than showing an error', async () => {
    api.questions.list.mockRejectedValue(
      Object.assign(new Error('aborted'), { name: 'AbortError' }),
    )

    const { result } = renderHook(() => useQuestionSearch(FILTERS))

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.error).toBeNull()
  })

  it('lets a caller patch a row in place via setItems', async () => {
    api.questions.list.mockResolvedValue({ items: [{ id: 1, tags: [] }], total: 1 })

    const { result } = renderHook(() => useQuestionSearch(FILTERS))
    await waitFor(() => expect(result.current.loading).toBe(false))

    act(() => {
      result.current.setItems(prev =>
        prev.map(it => (it.id === 1 ? { ...it, tags: [{ id: 9, name: 'hard' }] } : it)),
      )
    })

    expect(result.current.items[0].tags).toEqual([{ id: 9, name: 'hard' }])
  })
})
