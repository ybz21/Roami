import * as React from 'react'
import * as SelectPrimitive from '@radix-ui/react-select'
import { CheckIcon, ChevronDown, ChevronUp } from '../../icons'
import { cn } from './class-names'
export const Select = SelectPrimitive.Root
export const SelectValue = SelectPrimitive.Value
export const SelectTrigger = React.forwardRef<React.ElementRef<typeof SelectPrimitive.Trigger>, React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>>(({ className, children, ...props }, ref) => <SelectPrimitive.Trigger ref={ref} className={cn('ui-select-trigger mdl:flex mdl:items-center mdl:justify-between mdl:gap-2 mdl:rounded-xs mdl:text-body', className)} {...props}>{children}<SelectPrimitive.Icon asChild><ChevronDown /></SelectPrimitive.Icon></SelectPrimitive.Trigger>)
SelectTrigger.displayName = 'SelectTrigger'
export const SelectContent = React.forwardRef<React.ElementRef<typeof SelectPrimitive.Content>, React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>>(({ className, children, position = 'popper', ...props }, ref) => <SelectPrimitive.Portal><SelectPrimitive.Content ref={ref} position={position} sideOffset={4} className={cn('ui-select-content mdl:rounded-sm mdl:text-body', className)} {...props}><SelectPrimitive.ScrollUpButton className="ui-select-scroll"><ChevronUp /></SelectPrimitive.ScrollUpButton><SelectPrimitive.Viewport>{children}</SelectPrimitive.Viewport><SelectPrimitive.ScrollDownButton className="ui-select-scroll"><ChevronDown /></SelectPrimitive.ScrollDownButton></SelectPrimitive.Content></SelectPrimitive.Portal>)
SelectContent.displayName = 'SelectContent'
export const SelectItem = React.forwardRef<React.ElementRef<typeof SelectPrimitive.Item>, React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item>>(({ className, children, ...props }, ref) => <SelectPrimitive.Item ref={ref} className={cn('ui-select-item mdl:flex mdl:items-center mdl:gap-2 mdl:rounded-xs', className)} {...props}><span className="ui-select-check"><SelectPrimitive.ItemIndicator><CheckIcon /></SelectPrimitive.ItemIndicator></span><SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText></SelectPrimitive.Item>)
SelectItem.displayName = 'SelectItem'
