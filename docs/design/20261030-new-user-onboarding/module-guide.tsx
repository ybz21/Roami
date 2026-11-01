import { Button } from 'antd'
import { AppsIcon, BotIcon, ChevronRight, DeviceIcon, FileTextIcon, FolderIcon, GearIcon, GlobeIcon, HomeIcon, PlugIcon } from '../../../frontend/src/icons'

export const guideModules = [
  {
    id: 'home', title: '首页', icon: HomeIcon, summary: '和主智能体对话，安排工作、跟进结果。',
    location: '首页', when: '有一个需求想讨论，或想知道交出去的工作进展如何。',
    example: '帮我梳理个人网站需要哪些页面，先给方案。',
    sections: [
      { title: '主智能体', description: '理解你的需求，回答问题，并安排需要执行的任务。' },
      { title: '任务', description: '查看进行中的工作、需要你处理的事项，以及完成后的结果和文件。' },
      { title: '消息', description: '接收任务通知和提醒，查看后回到对应的工作。' },
      { title: '记忆', description: '查看和管理已记录的偏好、约定与项目知识，供后续工作参考。' },
    ],
    note: '先配置主智能体的模型服务，首页才能开始对话。', action: { label: '配置主智能体', page: 'model' },
  },
  {
    id: 'projects', title: '项目', icon: FolderIcon, summary: '按工作目录组织任务，和智能体一起推进项目。',
    location: '项目', when: '要让智能体在一个明确的目录里读文件、写代码或执行命令。',
    example: '在个人网站项目里，加一个作品展示页。',
    sections: [
      { title: '项目', description: '关联运行 Roami 的电脑上的一个目录，普通文件夹也可以。' },
      { title: '任务', description: '描述想完成的事，选择执行智能体，查看进展并验收结果。' },
      { title: '会话', description: '保留与智能体沟通和工作的现场，可以继续对话或查看终端。' },
      { title: 'Git 与工作区', description: 'Git 项目还可以使用分支和独立工作区，把不同任务的改动分开。' },
    ],
    note: '创建项目只是选好工作位置；点击开始任务后才会执行。', action: { label: '创建第一个项目', page: 'project' },
  },
  {
    id: 'capabilities', title: '能力', icon: PlugIcon, summary: '接入执行智能体，按需增加技能和外部服务。',
    location: '桌面：能力；手机：工具 / 能力', when: '想使用 Claude Code、Codex，或让智能体多一种工作方式。',
    example: '接入 Codex，让它处理项目里的开发任务。',
    sections: [
      { title: '智能体', description: '接入 Claude Code、Codex、OpenCode、Pi。它们负责在项目中执行具体任务。' },
      { title: 'Skills', description: '可复用的工作方法和说明，例如团队的代码审查规范。' },
      { title: 'MCP', description: '连接外部服务，让智能体使用该服务提供的操作和数据。' },
      { title: 'CLI', description: '把本机命令行能力接入智能体，供它按需调用。' },
      { title: '工具', description: '查看提供给智能体的具体操作，以及它们的说明和启用状态。' },
      { title: '插件', description: '安装和管理 Roami 扩展，增加功能入口或服务集成。' },
      { title: '市场', description: '发现可用的扩展来源，按需要选择和安装。' },
    ],
    note: '起步时接入一个执行智能体即可，其他能力可以用到时再加。', action: { label: '接入执行智能体', page: 'agents' },
  },
  {
    id: 'files', title: '文件', icon: FileTextIcon, summary: '查看、编辑工作文件，打开智能体交付的产物。',
    location: '桌面：文件；手机：工具 / 文件', when: '想直接检查代码、预览文档，或下载任务生成的文件。',
    example: '打开智能体生成的设计稿，看看实际效果。',
    sections: [
      { title: '浏览文件', description: '按目录找到运行 Roami 的电脑上的文件。' },
      { title: '查看与编辑', description: '阅读代码和文本，预览支持的文档与图片，按需编辑内容。' },
      { title: '交付文件', description: '从任务结果打开文件，查看或下载到当前设备。' },
    ],
    note: '这里展示的是当前 Roami 节点的文件；手机访问时也能查看。',
  },
  {
    id: 'browser', title: '浏览器', icon: GlobeIcon, summary: '在 Roami 中查看网页，检查页面和操作结果。',
    location: '桌面：浏览器；手机：工具 / 浏览器', when: '需要浏览资料、检查网页，或查看智能体正在操作的页面。',
    example: '打开项目页面，检查导航和表单是否正常。',
    sections: [
      { title: '网页与标签', description: '打开网页、切换标签，继续已有的浏览现场。' },
      { title: '页面检查', description: '查看网页的实际效果，配合任务完成页面检查。' },
    ],
    note: '浏览器运行在 Roami 节点上，登录和网页状态以该浏览器为准。',
  },
  {
    id: 'phone', title: '手机', icon: DeviceIcon, summary: '查看和控制连接到 Roami 电脑的 Android 设备。',
    location: '桌面：手机；手机端：工具 / 手机', when: '要在真实设备上体验应用，检查点按、滚动和键盘表现。',
    example: '在 Android 真机上检查刚完成的网页表单。',
    sections: [
      { title: '设备画面', description: '查看已连接设备的屏幕，确认当前页面和实际状态。' },
      { title: '触控操作', description: '在设备上点按、滑动和输入，检查真实交互。' },
    ],
    note: '需要先在运行 Roami 的电脑上连接设备并开启调试；这里不是当前访问页面的手机本身。',
  },
  {
    id: 'settings', title: '设置', icon: GearIcon, summary: '配置主智能体，以及节点、外观、通知和安全选项。',
    location: '设置', when: '首次配置模型，或想调整 Roami 的使用方式。',
    example: '设置主智能体的模型服务，再调整通知方式。',
    sections: [
      { title: '主智能体模型', description: '设置首页助手使用的服务地址、密钥和模型。' },
      { title: '外观与通知', description: '调整主题、语言、显示和通知偏好。' },
      { title: '节点与安全', description: '管理连接、访问和安全配置；节点是实际运行 Roami 和任务的电脑。' },
    ],
    note: 'Claude Code、Codex 等执行智能体的账号和模型在能力里分别配置。', action: { label: '配置主智能体', page: 'model' },
  },
] as const
export type GuideModuleId = typeof guideModules[number]['id']
export function readGuideModule(): GuideModuleId | null {
  const id = location.hash.split('/')[1]
  return guideModules.some(module => module.id === id) ? id as GuideModuleId : null
}

export function ModuleGuide({ phone, selected, onSelect, onSetup }: {
  phone: boolean; selected: GuideModuleId | null; onSelect: (id: GuideModuleId) => void;
  onSetup: (page: 'model' | 'agents' | 'project') => void;
}) {
  const current = guideModules.find(module => module.id === selected) || (phone ? null : guideModules[0])
  return <div className="module-guide">
    {!phone && <header className="tt-pagehead"><div className="ttl"><h2>认识 Roami</h2><p>了解每个模块的用途，用到时知道去哪里。</p></div></header>}
    {phone && !current && <p className="page-intro">点开一个模块，看看它能帮你做什么。</p>}
    <div className="guide-layout">
      {(!phone || !current) && <nav className="guide-list" aria-label="模块介绍">{guideModules.map(module => <button type="button" key={module.id} aria-current={current?.id === module.id ? 'page' : undefined} onClick={() => onSelect(module.id)}><module.icon size={22} /><span><strong>{module.title}</strong><small>{module.summary}</small></span><ChevronRight size={16} /></button>)}</nav>}
      {current && <article className="guide-detail" aria-label={`${current.title}介绍`}>
        <div className="guide-identity"><current.icon size={28} /><div>{!phone && <h3>{current.title}</h3>}<p>{current.summary}</p></div></div>
        <dl className="guide-facts"><div><dt>什么时候用</dt><dd>{current.when}</dd></div><div><dt>从哪里进入</dt><dd>{current.location}</dd></div></dl>
        <section className="guide-features" aria-label="模块功能">{current.sections.map(section => <div key={section.title}><h4>{section.title}</h4><p>{section.description}</p></div>)}</section>
        <section className="guide-example"><BotIcon size={18} /><div><h4>试着这样用</h4><p>{current.example}</p></div></section>
        <p className="guide-note">{current.note}</p>
        {'action' in current && <Button onClick={() => onSetup(current.action.page)}>{current.action.label}</Button>}
      </article>}
    </div>
    {phone && !current && <div className="quiet-note"><AppsIcon size={18} /><p>手机底栏保留首页、项目、工具和设置，文件、浏览器、手机与能力都在工具里。</p></div>}
  </div>
}
