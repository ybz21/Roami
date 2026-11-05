// @vitest-environment jsdom
import React from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { I18nProvider } from '../../i18n'
import { ProjectTree } from './ProjectTree'
import type { TreeTask } from './task-tree'

afterEach(cleanup)
const task = (path: string, name: string, sessions: TreeTask['sessions']): TreeTask => ({ key: `wt:${path}`, path, name, branch: 'fix/rsi', ahead: 0, unfinished: false, sessions })

it('shows recorded descendants under their parent and opens a child in its actual workspace', () => {
  const root = task('/rsi', 'RSI主任务', [{ name: 'parent', label: 'RSI修复', agent: 'codex' }, { name: 'child', label: '答案回归', parent: 'parent' }, { name: 'grandchild', label: '数值验证', parent: 'child' }])
  const separate = task('/verify', '独立验证', [{ name: 'cross', label: '跨区验证', parent: 'parent', agent: 'codex', at: Math.floor(Date.now() / 1000) - 180 }])
  const open = vi.fn()
  render(<I18nProvider><ProjectTree tree={{ projects: [{ key: 'p', name: 'Roami', dir: '/repo', needs: 0, tasks: [root, separate] }], loose: [] }} activeTask={separate.key} activeSession="cross" onProject={vi.fn()} onSession={open} /></I18nProvider>)
  const parent = screen.getByText('RSI修复').closest('.tt-tree-session-branch')!
  const child = screen.getByText('答案回归').closest('.tt-tree-session-branch')!
  const grandchild = screen.getByText('数值验证')
  expect(parent.querySelector('.tt-tree-children')?.contains(child)).toBe(true)
  expect(child.querySelector('.tt-tree-children')?.contains(grandchild)).toBe(true)
  const cross = screen.getByText('跨区验证').closest('button')!
  expect(parent.contains(cross)).toBe(true)
  expect(cross.querySelector('.tm')?.textContent).toBe('3m')
  expect(document.querySelector('.tt-tree .tt-session-location')).toBeNull()
  expect(screen.queryByText('fix/rsi')).toBeNull()
  expect(screen.queryByText('RSI主任务')).toBeNull()
  expect(screen.queryByText('独立验证')).toBeNull()
  expect(screen.queryByText(/工作区|Workspace|worktree/)).toBeNull()
  expect(cross.getAttribute('aria-current')).toBe('true')
  fireEvent.click(cross)
  expect(open).toHaveBeenCalledWith(separate.key, 'cross')
  expect(document.querySelectorAll('.tt-tree-row.on').length).toBe(1)
})

it('nests children across worktrees beneath a compact single-session parent without duplicating either', () => {
  const root = task('/rsi', 'RSI修复', [{ name: 'parent', label: 'RSI修复' }])
  const child = task('/check', 'RSI回归', [{ name: 'child', label: 'RSI回归', parent: 'parent' }])
  render(<ProjectTree tree={{ projects: [{ key: 'p', name: 'Roami', dir: '/repo', needs: 0, tasks: [root, child] }], loose: [] }} activeTask={null} activeSession={null} onProject={vi.fn()} onSession={vi.fn()} />)
  expect(screen.getAllByText('RSI修复').length).toBe(1)
  expect(screen.getAllByText('RSI回归').length).toBe(1)
  expect(screen.getByText('RSI修复').closest('.tt-tree-session-branch')?.querySelector('.tt-tree-children')?.contains(screen.getByText('RSI回归'))).toBe(true)
})

it('keeps unrelated sessions in one directory at the same level without a directory header', () => {
  const same = task('/same', '不应出现的目录标题', [{ name: 'a', label: '修复' }, { name: 'b', label: '独立检查' }])
  render(<ProjectTree tree={{ projects: [{ key: 'p', name: 'Roami', dir: '/repo', needs: 0, tasks: [same] }], loose: [] }} activeTask={null} activeSession={null} onProject={vi.fn()} onSession={vi.fn()} />)
  const roots = document.querySelector('.tt-tree-roots')!
  expect(roots.children.length).toBe(2)
  expect(screen.queryByText('不应出现的目录标题')).toBeNull()
  expect(document.querySelector('.tt-tree-children')).toBeNull()
})
