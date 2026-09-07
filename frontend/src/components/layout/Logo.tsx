import { Orbit } from "lucide-react";
export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2.5 whitespace-nowrap text-lg font-semibold tracking-tight">
      <Orbit
        size={29}
        strokeWidth={2.2}
        className="text-primary"
        aria-hidden="true"
      />
      {!compact && "行銷駕駛艙"}
    </span>
  );
}
