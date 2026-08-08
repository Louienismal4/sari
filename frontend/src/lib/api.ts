import type {
  Catalog,
  Dashboard,
  Item,
  ItemDraft,
  Movement,
  OCRHealth,
  ReceiptScan,
  StockMovementDraft,
} from "../types";

const API_ORIGIN = (import.meta.env.VITE_API_BASE_URL ?? "").trim().replace(/\/+$/, "");
const API_ROOT = `${API_ORIGIN}/api/v1`;

type ValidationIssue = { loc?: Array<string | number>; msg?: string };

function apiErrorMessage(body: unknown, status: number): string {
  if (!body || typeof body !== "object" || !("detail" in body)) return `Request failed with status ${status}`;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((issue: ValidationIssue) => {
        if (!issue?.msg) return null;
        const field = issue.loc?.filter((part) => part !== "body").join(" → ");
        return field ? `${field}: ${issue.msg}` : issue.msg;
      })
      .filter(Boolean);
    if (messages.length) return messages.join(". ");
  }
  return `Request failed with status ${status}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(apiErrorMessage(body, response.status));
  }
  return (await response.json()) as T;
}

export async function getDashboard(): Promise<Dashboard> {
  return request<Dashboard>("/dashboard");
}

export async function getOcrHealth(): Promise<OCRHealth> {
  return request<OCRHealth>("/ocr/health");
}

export async function getCatalog(): Promise<Catalog> {
  return request<Catalog>("/catalog");
}

export async function getItems(params?: { query?: string; lowStock?: boolean; includeArchived?: boolean }): Promise<Item[]> {
  const search = new URLSearchParams();
  if (params?.query) search.set("q", params.query);
  if (params?.lowStock) search.set("low_stock", "true");
  if (params?.includeArchived) search.set("include_archived", "true");
  const result = await request<{ data: Item[] }>(`/items${search.size ? `?${search.toString()}` : ""}`);
  return result.data;
}

export async function createItem(draft: ItemDraft): Promise<Item> {
  return request<Item>("/items", { method: "POST", body: JSON.stringify(draft) });
}

export async function updateItem(itemId: string, draft: Partial<ItemDraft> & { is_active?: boolean }): Promise<Item> {
  return request<Item>(`/items/${itemId}`, { method: "PATCH", body: JSON.stringify(draft) });
}

export async function archiveItem(itemId: string): Promise<Item> {
  return request<Item>(`/items/${itemId}/archive`, { method: "POST" });
}

export async function getItemMovements(itemId: string): Promise<Movement[]> {
  const result = await request<{ data: Movement[] }>(`/items/${itemId}/movements`);
  return result.data;
}

export async function getInventory(): Promise<Item[]> {
  const result = await request<{ data: Item[] }>("/inventory");
  return result.data;
}

export async function createStockMovement(draft: StockMovementDraft): Promise<Movement> {
  return request<Movement>("/stock-movements", { method: "POST", body: JSON.stringify(draft) });
}

export async function getReceiptScans(): Promise<ReceiptScan[]> {
  const result = await request<{ data: ReceiptScan[] }>("/receipt-scans");
  return result.data;
}

export async function updateReceiptScan(scanId: string, payload: { purchased_at?: string | null }): Promise<ReceiptScan> {
  return request<ReceiptScan>(`/receipt-scans/${scanId}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export async function retryReceiptScan(scanId: string): Promise<ReceiptScan> {
  return request<ReceiptScan>(`/receipt-scans/${scanId}/retry`, { method: "POST" });
}

export async function createReceiptScan(file?: File): Promise<ReceiptScan> {
  const body = new FormData();
  if (file) body.append("file", file);
  return request<ReceiptScan>("/receipt-scans", { method: "POST", body });
}

export async function updateReceiptLine(
  scanId: string,
  lineId: string,
  payload: { matched_item_id?: string | null; unit_id?: string | null; quantity?: string; unit_cost?: string; expiry_date?: string | null },
): Promise<ReceiptScan> {
  return request<ReceiptScan>(`/receipt-scans/${scanId}/lines/${lineId}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export async function confirmReceiptScan(scanId: string): Promise<{ scan_id: string; status: string; movements_created: number; total: string }> {
  return request(`/receipt-scans/${scanId}/confirm`, { method: "POST" });
}
