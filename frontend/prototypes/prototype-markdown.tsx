import React from 'react'
import ReactMarkdown from 'react-markdown'
export default function PrototypeMarkdown({ children }: { children: string }) { return <div className="markdown-body"><ReactMarkdown>{children}</ReactMarkdown></div> }
