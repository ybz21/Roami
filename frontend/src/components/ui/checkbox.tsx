import * as React from 'react'
import * as CheckboxPrimitive from '@radix-ui/react-checkbox'
import { CheckIcon, MinusIcon } from '../../icons'
import { cn } from './class-names'
export const Checkbox = React.forwardRef<React.ElementRef<typeof CheckboxPrimitive.Root>, React.ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>>(({ className, checked, ...props }, ref) => <CheckboxPrimitive.Root ref={ref} checked={checked} className={cn('ui-checkbox mdl:inline-flex mdl:items-center mdl:justify-center mdl:rounded-xs', className)} {...props}><CheckboxPrimitive.Indicator>{checked === 'indeterminate' ? <MinusIcon /> : <CheckIcon />}</CheckboxPrimitive.Indicator></CheckboxPrimitive.Root>)
Checkbox.displayName = 'Checkbox'
