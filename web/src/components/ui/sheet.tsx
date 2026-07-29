import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "../../lib/utils";
import { DialogOverlay } from "./dialog";

export const Sheet = DialogPrimitive.Root;
export const SheetTrigger = DialogPrimitive.Trigger;
export const SheetClose = DialogPrimitive.Close;
export const SheetContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
>(({ className, children, ...props }, ref) => (
  <DialogPrimitive.Portal>
    <DialogOverlay />
    <DialogPrimitive.Content ref={ref} className={cn("shadcn-sheet-content", className)} {...props}>
      {children}
      <DialogPrimitive.Close className="shadcn-dialog-close" aria-label="Close"><X size={18} /></DialogPrimitive.Close>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
));
SheetContent.displayName = DialogPrimitive.Content.displayName;
export function SheetHeader(props: React.HTMLAttributes<HTMLDivElement>) { return <div {...props} className={cn("shadcn-sheet-header", props.className)} />; }
export function SheetFooter(props: React.HTMLAttributes<HTMLDivElement>) { return <div {...props} className={cn("shadcn-sheet-footer", props.className)} />; }
export const SheetTitle = DialogPrimitive.Title;
export const SheetDescription = DialogPrimitive.Description;
