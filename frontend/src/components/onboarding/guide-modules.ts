import { HomeIcon, FolderIcon, PlugIcon, FileTextIcon, GearIcon } from '../../icons'
export const guideModules = [
  { id: 'home', icon: HomeIcon, features: 4 },
  { id: 'projects', icon: FolderIcon, features: 4 },
  { id: 'capabilities', icon: PlugIcon, features: 8 },
  { id: 'files', icon: FileTextIcon, features: 3 },
  { id: 'settings', icon: GearIcon, features: 3 },
] as const
export type GuideModuleId = typeof guideModules[number]['id']
