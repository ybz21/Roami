import { HomeIcon, FolderIcon, PlugIcon, FileTextIcon, GlobeIcon, DeviceIcon, GearIcon } from '../../icons'
export const guideModules = [
  { id: 'home', icon: HomeIcon, features: 4 },
  { id: 'projects', icon: FolderIcon, features: 4 },
  { id: 'capabilities', icon: PlugIcon, features: 8 },
  { id: 'files', icon: FileTextIcon, features: 3 },
  { id: 'browser', icon: GlobeIcon, features: 2 },
  { id: 'phone', icon: DeviceIcon, features: 2 },
  { id: 'settings', icon: GearIcon, features: 3 },
] as const
export type GuideModuleId = typeof guideModules[number]['id']
