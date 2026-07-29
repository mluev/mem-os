import * as React from "react";
import { Command as CommandPrimitive } from "cmdk";
import { Search } from "lucide-react";
import { cn } from "../../lib/utils";
export const Command = React.forwardRef<React.ElementRef<typeof CommandPrimitive>, React.ComponentPropsWithoutRef<typeof CommandPrimitive>>(({ className, ...props }, ref) => <CommandPrimitive ref={ref} className={cn("shadcn-command", className)} {...props} />);
Command.displayName = CommandPrimitive.displayName;
export function CommandInput(props: React.ComponentPropsWithoutRef<typeof CommandPrimitive.Input>) { return <div className="shadcn-command-input-wrap"><Search size={16} /><CommandPrimitive.Input className="shadcn-command-input" {...props} /></div>; }
export const CommandList = React.forwardRef<React.ElementRef<typeof CommandPrimitive.List>, React.ComponentPropsWithoutRef<typeof CommandPrimitive.List>>(({ className, ...props }, ref) => <CommandPrimitive.List ref={ref} className={cn("shadcn-command-list", className)} {...props} />);
CommandList.displayName = CommandPrimitive.List.displayName;
export const CommandEmpty = CommandPrimitive.Empty;
export const CommandGroup = React.forwardRef<React.ElementRef<typeof CommandPrimitive.Group>, React.ComponentPropsWithoutRef<typeof CommandPrimitive.Group>>(({ className, ...props }, ref) => <CommandPrimitive.Group ref={ref} className={cn("shadcn-command-group", className)} {...props} />);
CommandGroup.displayName = CommandPrimitive.Group.displayName;
export const CommandItem = React.forwardRef<React.ElementRef<typeof CommandPrimitive.Item>, React.ComponentPropsWithoutRef<typeof CommandPrimitive.Item>>(({ className, ...props }, ref) => <CommandPrimitive.Item ref={ref} className={cn("shadcn-command-item", className)} {...props} />);
CommandItem.displayName = CommandPrimitive.Item.displayName;
