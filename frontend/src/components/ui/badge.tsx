import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";


const badgeVariants = cva(
  "inline-flex w-fit items-center rounded-full px-3 py-1 text-xs font-medium",
  {
    variants: {
      variant: {
        soft: "bg-teal-50 text-teal-800 ring-1 ring-teal-200",
        outline: "bg-white/92 text-slate-800 ring-1 ring-teal-200",
        status: "bg-slate-900/90 text-white",
      },
    },
    defaultVariants: {
      variant: "soft",
    },
  },
);

export interface BadgeProps
  extends HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}
