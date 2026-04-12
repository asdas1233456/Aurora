import type { ComponentProps, ReactNode } from "react";

import { motion, useReducedMotion } from "framer-motion";
import type { LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";


interface EmptyStateAction {
  label: string;
  onClick: () => void;
  icon?: LucideIcon;
  variant?: ComponentProps<typeof Button>["variant"];
  testId?: string;
}

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  actions?: EmptyStateAction[];
  children?: ReactNode;
  className?: string;
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  actions = [],
  children,
  className,
}: EmptyStateProps) {
  const reducedMotion = useReducedMotion();

  return (
    <motion.div
      initial={reducedMotion ? undefined : { opacity: 0, y: 12, scale: 0.98 }}
      animate={reducedMotion ? undefined : { opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.28, ease: "easeOut" }}
      className={cn(
        "relative overflow-hidden rounded-[28px] border border-dashed border-teal-200/90 bg-[radial-gradient(circle_at_top,_rgba(255,255,255,0.95),_rgba(236,247,246,0.86)_48%,_rgba(222,243,241,0.92)_100%)] px-6 py-8 text-center shadow-[inset_0_1px_0_rgba(255,255,255,0.8)]",
        className,
      )}
    >
      <div className="pointer-events-none absolute inset-x-8 top-0 h-28 rounded-b-[999px] bg-[linear-gradient(180deg,rgba(125,211,252,0.16),rgba(255,255,255,0))]" />
      <div className="pointer-events-none absolute left-8 top-10 h-2 w-2 rounded-full bg-teal-300/80 shadow-[0_0_0_8px_rgba(20,184,166,0.08)]" />
      <div className="pointer-events-none absolute right-10 top-16 h-2.5 w-2.5 rounded-full bg-cyan-300/80 shadow-[0_0_0_10px_rgba(125,211,252,0.08)]" />

      <div className="relative mx-auto flex max-w-lg flex-col items-center">
        <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-[22px] border border-white/80 bg-white/88 text-teal-700 shadow-[0_16px_30px_rgba(15,118,110,0.12)] backdrop-blur-xl">
          <Icon className="h-7 w-7" />
        </div>
        <h3 className="mt-3 font-display text-[1.9rem] leading-tight text-slate-900">
          {title}
        </h3>
        <p className="mt-3 max-w-md text-sm leading-7 text-slate-500">
          {description}
        </p>

        {children ? <div className="mt-5 w-full">{children}</div> : null}

        {actions.length > 0 ? (
          <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
            {actions.map(({ label, onClick, icon: ActionIcon, variant = "secondary", testId }) => (
              <Button
                key={label}
                type="button"
                variant={variant}
                onClick={onClick}
                data-testid={testId}
              >
                {ActionIcon ? <ActionIcon className="h-4 w-4" /> : null}
                {label}
              </Button>
            ))}
          </div>
        ) : null}
      </div>
    </motion.div>
  );
}
