import { useState } from "react";
import { CalendarDays, X } from "lucide-react";
import { Button } from "./button";
import { Calendar } from "./calendar";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";

export function DatePicker({
  value,
  onChange,
}: {
  value?: string | null;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const selected = value ? new Date(value) : undefined;
  const setDays = (days: number) => {
    const date = new Date();
    date.setDate(date.getDate() + days);
    onChange(date.toISOString());
    setOpen(false);
  };
  return (
    <div className="date-picker-row">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button type="button" variant="secondary" className="date-picker-trigger">
            <CalendarDays size={14} />
            {selected && !Number.isNaN(selected.getTime())
              ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(selected)
              : "No expiration"}
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="calendar-popover">
          <Calendar
            mode="single"
            selected={selected}
            onSelect={(day) => {
              if (day) onChange(day.toISOString());
              setOpen(false);
            }}
          />
          <div className="calendar-presets">
            <Button type="button" size="sm" variant="ghost" onClick={() => setDays(1)}>+1d</Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setDays(7)}>+7d</Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setDays(30)}>+30d</Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => { onChange(""); setOpen(false); }}><X size={12} /> Never</Button>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
