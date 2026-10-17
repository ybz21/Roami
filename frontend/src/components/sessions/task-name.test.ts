import { describe, expect, it } from 'vitest'
import { taskNameFromPrompt } from './NewSessionModal'

// 这个名字只是占位——真名字由 agent 开工后 roami session rename。但占位也不能难看到
// 「你去英伟达的-DGX-Spark」这种：半个词吊在末尾，开头两个字还只是在说「有人在派活」。
describe('taskNameFromPrompt：派生占位名', () => {
  it('剥掉开头的人称与招呼', () => {
    expect(taskNameFromPrompt('帮我把登录页的报错提示改一下')).toBe('把登录页的报错提示改一下')
    expect(taskNameFromPrompt('请修一下终端复制粘贴')).toBe('修一下终端复制粘贴')
  })
  it('在首个标点处断句', () => {
    expect(taskNameFromPrompt('修一下状态条，顺便把版本号补上')).toBe('修一下状态条')
  })
  it('不把拉丁词切成半个', () => {
    const n = taskNameFromPrompt('你去英伟达的 DGX Spark 论坛上找一下 GLM 5.3 Flash 的部署方案')
    expect(n.endsWith('Spar')).toBe(false)
    expect(n).toBe('英伟达的-DGX-Spark')
  })
  it('尾部标点和连字符不留', () => {
    expect(taskNameFromPrompt('把 swap 清空。')).toBe('把-swap-清空')
  })
  it('整句都是招呼时不至于空掉', () => {
    expect(taskNameFromPrompt('你').length).toBeGreaterThan(0)
  })
})
