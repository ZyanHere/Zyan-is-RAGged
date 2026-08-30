import type { DocumentStatus } from "@/types";
import { Badge } from "@/components/ui/Badge";

interface DocumentStatusBadgeProps {
  status: DocumentStatus;
}

const STATUS_CONFIG: Record<DocumentStatus, { label: string; variant: "default" | "success" | "warning" | "error" | "info" }> = {
  idle:       { label: "Queued",     variant: "default" },
  uploading:  { label: "Uploading",  variant: "info"    },
  processing: { label: "Processing", variant: "warning" },
  ready:      { label: "Ready",      variant: "success" },
  error:      { label: "Error",      variant: "error"   },
};

export function DocumentStatusBadge({ status }: DocumentStatusBadgeProps) {
  const { label, variant } = STATUS_CONFIG[status];
  return (
    <Badge variant={variant}>
      {status === "processing" && (
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
      )}
      {label}
    </Badge>
  );
}
