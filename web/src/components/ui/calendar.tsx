import { DayPicker, type DayPickerProps } from "react-day-picker";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "../../lib/utils";

export function Calendar({ className, ...props }: DayPickerProps) {
  return (
    <DayPicker
      className={cn("shadcn-calendar", className)}
      classNames={{
        months: "calendar-months",
        month: "calendar-month",
        month_caption: "calendar-caption",
        caption_label: "calendar-caption-label",
        nav: "calendar-nav",
        button_previous: "calendar-nav-button",
        button_next: "calendar-nav-button",
        month_grid: "calendar-grid",
        weekdays: "calendar-weekdays",
        weekday: "calendar-weekday",
        week: "calendar-week",
        day: "calendar-day",
        day_button: "calendar-day-button",
        selected: "calendar-selected",
        today: "calendar-today",
        outside: "calendar-outside",
        disabled: "calendar-disabled",
      }}
      components={{
        Chevron: ({ orientation }) => orientation === "left" ? <ChevronLeft size={14} /> : <ChevronRight size={14} />,
      }}
      {...props}
    />
  );
}
