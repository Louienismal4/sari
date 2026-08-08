export function formatMoney(value: string | number | null | undefined): string {
  return new Intl.NumberFormat("en-PH", { style: "currency", currency: "PHP", minimumFractionDigits: 2 }).format(Number(value ?? 0));
}

export function formatQuantity(value: string | number | null | undefined): string {
  return new Intl.NumberFormat("en-PH", { maximumFractionDigits: 3 }).format(Number(value ?? 0));
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-PH", { month: "short", day: "numeric", year: "numeric" }).format(new Date(value));
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-PH", { hour: "numeric", minute: "2-digit" }).format(new Date(value));
}

export function formatMovementLabel(type: string): string {
  switch (type) {
    case "RECEIPT_IN":
      return "Stock received";
    case "MANUAL_IN":
      return "Stock received";
    case "MANUAL_OUT":
      return "Stock removed";
    case "ADJUSTMENT":
      return "Physical count";
    default:
      return type.replaceAll("_", " ").toLowerCase();
  }
}

export function isPositiveMovement(type: string, delta: string): boolean {
  return Number(delta) >= 0 && type !== "MANUAL_OUT";
}

