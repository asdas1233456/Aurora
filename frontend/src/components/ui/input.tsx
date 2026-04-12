import * as React from "react";

import { cn } from "@/lib/utils";


export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-11 w-full rounded-2xl border border-teal-100 bg-white/90 px-4 text-sm text-slate-900 outline-none ring-0 transition placeholder:text-slate-500 focus:border-teal-500 focus:bg-white",
        className,
      )}
      {...props}
    />
  ),
);

Input.displayName = "Input";
