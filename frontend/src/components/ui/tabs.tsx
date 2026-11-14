import * as React from 'react'
import * as TabsPrimitive from '@radix-ui/react-tabs'
import { cn } from './class-names'
export const Tabs = TabsPrimitive.Root
export const TabsContent = TabsPrimitive.Content
export const TabsList = React.forwardRef<React.ElementRef<typeof TabsPrimitive.List>, React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>>(({ className, ...props }, ref) => <TabsPrimitive.List ref={ref} className={cn('ui-tabs-list mdl:flex mdl:items-center mdl:gap-1', className)} {...props} />)
TabsList.displayName = 'TabsList'
export const TabsTrigger = React.forwardRef<React.ElementRef<typeof TabsPrimitive.Trigger>, React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>>(({ className, ...props }, ref) => <TabsPrimitive.Trigger ref={ref} className={cn('ui-tabs-trigger mdl:rounded-xs mdl:text-sm mdl:font-medium', className)} {...props} />)
TabsTrigger.displayName = 'TabsTrigger'
