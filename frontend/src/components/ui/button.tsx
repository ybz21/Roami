import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from './class-names'
const buttonVariants = cva('mdl:inline-flex mdl:items-center mdl:justify-center mdl:gap-2 mdl:rounded-xs mdl:text-sm mdl:font-medium mdl:whitespace-nowrap mdl:disabled:pointer-events-none mdl:disabled:opacity-50 ui-button', {
  variants: { variant: { default: 'ui-button-primary', outline: 'ui-button-outline', ghost: 'ui-button-ghost', destructive: 'ui-button-danger', link: 'ui-button-link' }, size: { default: 'ui-button-default', icon: 'ui-button-icon', sm: 'ui-button-small' } },
  defaultVariants: { variant: 'outline', size: 'default' },
})
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> { asChild?: boolean }
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, asChild = false, type = 'button', ...props }, ref) => {
  const Comp = asChild ? Slot : 'button'
  return <Comp ref={ref} type={asChild ? undefined : type} className={cn(buttonVariants({ variant, size }), className)} {...props} />
})
Button.displayName = 'Button'
