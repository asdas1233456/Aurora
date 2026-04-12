import * as React from "react";

import { cn } from "@/lib/utils";


export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      "min-h-[124px] w-full rounded-[24px] border border-teal-100 bg-white/90 px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-500 focus:border-teal-500 focus:bg-white",
      className,
    )}
    {...props}
  />
));

Textarea.displayName = "Textarea";
