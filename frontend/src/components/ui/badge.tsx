import type { HTMLAttributes } from 'react'
import { cn } from './class-names'
export function Badge({ className, ...props }: HTMLAttributes<HTMLSpanElement>) { return <span className={cn('ui-badge mdl:inline-flex mdl:items-center mdl:gap-1 mdl:rounded-pill mdl:text-meta', className)} {...props} /> }
