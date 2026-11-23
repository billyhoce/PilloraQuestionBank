import { createContext, useContext } from 'react'

export const UploadQueueContext = createContext(null)

// The upload queue (UploadQueue.jsx), or null outside an UploadQueueProvider (e.g. a component
// under test on its own).
export function useUploadQueue() {
  return useContext(UploadQueueContext)
}
