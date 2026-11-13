import { createContext, useContext, useEffect, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react'

export type FilePageMemory = Map<string, unknown>
const FilePageContext = createContext<FilePageMemory | undefined>(undefined)

// Owned by the app shell: navigation unmounts pages, but each node keeps its workspace.
export function useFilePageMemory(node: string | null) {
  const nodes = useRef(new Map<string | null, FilePageMemory>())
  let memory = nodes.current.get(node)
  if (!memory) { memory = new Map(); nodes.current.set(node, memory) }
  return memory
}

export function FilePageMemoryProvider({ memory, children }: { memory?: FilePageMemory; children: ReactNode }) {
  return <FilePageContext.Provider value={memory}>{children}</FilePageContext.Provider>
}

export function useFilePageState<T,>(key: string, initial: T | (() => T)): [T, Dispatch<SetStateAction<T>>] {
  const memory = useContext(FilePageContext)
  const [value, setValue] = useState<T>(() => memory?.has(key) ? memory.get(key) as T : typeof initial === 'function' ? (initial as () => T)() : initial)
  useEffect(() => { memory?.set(key, value) }, [key, memory, value])
  return [value, setValue]
}

export function useForgetFilePageView() {
  const memory = useContext(FilePageContext)
  return (path: string, preview = false) => {
    const prefix = `view:${JSON.stringify(path)}:${preview ? 'preview' : 'file'}:`
    for (const key of memory?.keys() || []) if (key.startsWith(prefix)) memory?.delete(key)
  }
}
