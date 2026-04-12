import * as SliderPrimitive from "@radix-ui/react-slider";

import { cn } from "@/lib/utils";


export function Slider({
  className,
  ...props
}: React.ComponentPropsWithoutRef<typeof SliderPrimitive.Root>) {
  return (
    <SliderPrimitive.Root
      className={cn("relative flex w-full touch-none select-none items-center", className)}
      {...props}
    >
      <SliderPrimitive.Track className="relative h-2 w-full grow overflow-hidden rounded-full bg-teal-100">
        <SliderPrimitive.Range className="absolute h-full bg-gradient-to-r from-teal-600 to-cyan-400" />
      </SliderPrimitive.Track>
      <SliderPrimitive.Thumb className="block h-5 w-5 rounded-full border-2 border-white bg-teal-700 shadow-lg transition hover:scale-105 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/60" />
    </SliderPrimitive.Root>
  );
}
