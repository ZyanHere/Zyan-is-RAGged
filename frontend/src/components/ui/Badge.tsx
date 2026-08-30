import { cn } from "@/lib/utils";

interface BadgeProps {
  children: React.ReactNode;
  variant?: "default" | "success" | "warning" | "error" | "info";
  className?: string;
}

const variantStyles: Record<NonNullable<BadgeProps["variant"]>, string> = {
  default:  "bg-neutral-100 text-neutral-600",
  success:  "bg-emerald-50  text-emerald-700",
  warning:  "bg-amber-50    text-amber-700",
  error:    "bg-red-50      text-red-700",
  info:     "bg-blue-50     text-blue-700",
};

export function Badge({ children, variant = "default", className }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        variantStyles[variant],
        className
      )}
    >
      {children}
    </span>
  );
}
