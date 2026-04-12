import * as AlertDialogPrimitive from "@radix-ui/react-alert-dialog";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";


export const AlertDialog = AlertDialogPrimitive.Root;
export const AlertDialogTrigger = AlertDialogPrimitive.Trigger;
export const AlertDialogCancel = AlertDialogPrimitive.Cancel;
export const AlertDialogAction = AlertDialogPrimitive.Action;

export function AlertDialogContent({
  className,
  children,
  ...props
}: React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Content>) {
  return (
    <AlertDialogPrimitive.Portal>
      <AlertDialogPrimitive.Overlay className="fixed inset-0 z-50 bg-slate-950/30 backdrop-blur-sm" />
      <AlertDialogPrimitive.Content
        className={cn(
          "fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-[28px] border border-white/70 bg-white/94 p-6 shadow-[0_30px_100px_rgba(15,118,110,0.24)] backdrop-blur-2xl",
          className,
        )}
        {...props}
      >
        {children}
      </AlertDialogPrimitive.Content>
    </AlertDialogPrimitive.Portal>
  );
}

export function AlertDialogHeader({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("mb-4 flex flex-col gap-1.5", className)} {...props} />;
}

export function AlertDialogTitle({
  className,
  ...props
}: React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Title>) {
  return <AlertDialogPrimitive.Title className={cn("text-lg font-semibold text-slate-900", className)} {...props} />;
}

export function AlertDialogDescription({
  className,
  ...props
}: React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Description>) {
  return <AlertDialogPrimitive.Description className={cn("text-sm leading-6 text-slate-500", className)} {...props} />;
}

export function AlertDialogFooter({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("mt-6 flex justify-end gap-3", className)} {...props} />;
}

export const AlertDialogCancelButton = AlertDialogCancel;
export const AlertDialogActionButton = AlertDialogAction;

export function AlertDialogCancelControl(props: React.ComponentProps<typeof Button>) {
  return (
    <AlertDialogCancel asChild>
      <Button variant="secondary" {...props} />
    </AlertDialogCancel>
  );
}

export function AlertDialogActionControl(props: React.ComponentProps<typeof Button>) {
  return (
    <AlertDialogAction asChild>
      <Button variant="destructive" {...props} />
    </AlertDialogAction>
  );
}
