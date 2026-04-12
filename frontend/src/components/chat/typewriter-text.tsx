import { useEffect, useState } from "react";

import { motion, useReducedMotion } from "framer-motion";

import { clamp, cn } from "@/lib/utils";


interface TypewriterTextProps {
  content: string;
  animate?: boolean;
  streaming?: boolean;
  className?: string;
  placeholder?: string;
}

export function TypewriterText({
  content,
  animate = false,
  streaming = false,
  className,
  placeholder = "...",
}: TypewriterTextProps) {
  const reducedMotion = useReducedMotion();
  const shouldAnimate = animate && !reducedMotion;
  const [visibleCount, setVisibleCount] = useState(() =>
    shouldAnimate ? 0 : content.length,
  );

  useEffect(() => {
    if (!shouldAnimate) {
      setVisibleCount(content.length);
      return;
    }

    setVisibleCount((current) => clamp(current, 0, content.length));
  }, [content.length, shouldAnimate]);

  useEffect(() => {
    if (!shouldAnimate || visibleCount >= content.length) {
      return;
    }

    const step = Math.max(1, Math.ceil((content.length - visibleCount) / 18));
    const interval = window.setInterval(() => {
      setVisibleCount((current) => {
        const next = Math.min(content.length, current + step);
        if (next >= content.length) {
          window.clearInterval(interval);
        }
        return next;
      });
    }, streaming ? 18 : 12);

    return () => window.clearInterval(interval);
  }, [content.length, shouldAnimate, streaming, visibleCount]);

  const resolvedText = shouldAnimate ? content.slice(0, visibleCount) : content;
  const showCursor = shouldAnimate && (streaming || visibleCount < content.length);

  return (
    <span className={cn("whitespace-pre-wrap break-words", className)}>
      {resolvedText || placeholder}
      {showCursor ? (
        <motion.span
          animate={{ opacity: [0.25, 1, 0.25] }}
          transition={{ duration: 0.9, repeat: Number.POSITIVE_INFINITY, ease: "easeInOut" }}
          className="ml-0.5 inline-block text-teal-700"
          aria-hidden="true"
        >
          |
        </motion.span>
      ) : null}
    </span>
  );
}
