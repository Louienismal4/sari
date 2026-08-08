export type ViewKey = "overview" | "items" | "stock" | "receipts";

export type StockStatus = "healthy" | "low_stock" | "out_of_stock";

export interface CatalogCategory {
  id: string;
  name: string;
  description?: string | null;
}

export interface CatalogUnit {
  id: string;
  name: string;
  abbreviation: string;
  allows_decimal: boolean;
}

export interface CatalogSupplier {
  id: string;
  name: string;
}

export interface Catalog {
  categories: CatalogCategory[];
  units: CatalogUnit[];
  suppliers: CatalogSupplier[];
}

export interface Item {
  id: string;
  item_code: string;
  name: string;
  category_id: string;
  category_name: string | null;
  unit_id: string;
  unit_name: string | null;
  unit_abbreviation: string | null;
  selling_unit_id: string;
  selling_unit_name: string | null;
  selling_unit_abbreviation: string | null;
  units_per_purchase_unit: string;
  cost_per_selling_unit: string;
  selling_units_on_hand: string;
  profit_per_selling_unit: string;
  projected_profit: string;
  gross_margin_percent: string;
  primary_supplier_id: string | null;
  supplier_name: string | null;
  unit_cost: string;
  markup_percent: string;
  suggested_price: string;
  actual_selling_price: string;
  reorder_level: string;
  stock_on_hand: string;
  stock_status: StockStatus;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Movement {
  id: string;
  item_id: string;
  item_name: string | null;
  movement_type: "RECEIPT_IN" | "MANUAL_IN" | "MANUAL_OUT" | "ADJUSTMENT" | string;
  quantity_delta: string;
  unit_cost: string | null;
  purchase_date: string | null;
  expiry_date: string | null;
  source: string;
  reference: string | null;
  notes: string | null;
  actor: string;
  created_at: string;
}

export interface Dashboard {
  metrics: {
    active_items: number;
    units_on_hand: string;
    inventory_value: string;
    low_stock: number;
  };
  low_stock_items: Item[];
  recent_movements: Movement[];
  ocr: {
    status: "online" | "offline" | string;
    provider: string;
    message: string;
  };
}

export interface OCRHealth {
  status: "online" | "offline" | string;
  provider: string;
  message: string;
}

export interface ReceiptLine {
  id: string;
  raw_text: string;
  name: string;
  unit_id: string | null;
  unit_name: string | null;
  unit_abbreviation: string | null;
  quantity: string;
  unit_cost: string;
  line_total: string;
  expiry_date: string | null;
  confidence: string;
  matched_item_id: string | null;
  matched_item_name: string | null;
  review_status: "REVIEW" | "READY" | "IGNORE" | string;
}

export interface ReceiptScan {
  id: string;
  original_filename: string;
  status: "WAITING_FOR_SERVICE" | "REVIEW" | "CONFIRMED" | "FAILED" | string;
  provider: string;
  provider_request_id: string | null;
  merchant_name: string | null;
  receipt_number: string | null;
  purchased_at: string | null;
  currency: string;
  total: string | null;
  error: string | null;
  attempt_count: number;
  last_attempt_at: string | null;
  next_retry_at: string | null;
  gateway_error_code: string | null;
  can_retry: boolean;
  warnings: string[];
  created_at: string;
  updated_at: string;
  lines: ReceiptLine[];
}

export interface ItemDraft {
  item_code?: string;
  name: string;
  category_id: string;
  unit_id: string;
  selling_unit_id?: string;
  units_per_purchase_unit: string;
  primary_supplier_id?: string;
  unit_cost: string;
  markup_percent: string;
  actual_selling_price?: string;
  reorder_level: string;
}

export interface StockMovementDraft {
  item_id: string;
  movement_type: "RECEIPT_IN" | "MANUAL_IN" | "MANUAL_OUT" | "ADJUSTMENT";
  quantity: string;
  quantity_delta?: string;
  unit_cost?: string;
  purchase_date?: string;
  expiry_date?: string;
  source: string;
  reference?: string;
  notes?: string;
  idempotency_key?: string;
}
