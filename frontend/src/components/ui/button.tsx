import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";


const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full text-sm font-medium transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-teal-700 text-white shadow-[0_12px_30px_rgba(15,118,110,0.24)] hover:bg-teal-800",
        secondary: "bg-white/70 text-slate-800 ring-1 ring-white/70 hover:bg-white",
        ghost: "bg-transparent text-slate-700 hover:bg-teal-50 hover:text-teal-800",
        outline: "bg-white/65 text-slate-800 ring-1 ring-teal-200 hover:bg-white",
        destructive: "bg-rose-600 text-white hover:bg-rose-700",
      },
      size: {
        sm: "h-9 px-3.5",
        default: "h-10 px-4",
        lg: "h-11 px-5",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />
  ),
);

Button.displayName = "Button";
