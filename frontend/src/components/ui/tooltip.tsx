import * as TooltipPrimitive from "@radix-ui/react-tooltip";

import { cn } from "@/lib/utils";


export const TooltipProvider = TooltipPrimitive.Provider;
export const Tooltip = TooltipPrimitive.Root;
export const TooltipTrigger = TooltipPrimitive.Trigger;

export function TooltipContent({
  className,
  sideOffset = 6,
  ...props
}: React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        sideOffset={sideOffset}
        className={cn(
          "z-50 rounded-2xl bg-slate-900 px-3 py-2 text-xs text-white shadow-xl",
          className,
        )}
        {...props}
      />
    </TooltipPrimitive.Portal>
  );
}
