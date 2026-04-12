import type { ReactNode } from "react";

import { Info } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";


export function TitleInfoIcon({
  children,
  label = "标题说明",
  className,
}: {
  children: ReactNode;
  label?: string;
  className?: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={label}
          className={cn(
            "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-lg border border-teal-100 bg-white/82 text-teal-700 shadow-[inset_0_1px_0_rgba(255,255,255,0.86)] transition hover:border-teal-300 hover:bg-teal-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/50",
            className,
          )}
        >
          <Info className="h-3.5 w-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent side="top" align="start" className="max-w-[20rem] rounded-lg px-3 py-2 text-[12px] leading-5">
        {children}
      </TooltipContent>
    </Tooltip>
  );
}
