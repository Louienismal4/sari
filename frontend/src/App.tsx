import { useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "./components/AppShell";
import { DashboardPage } from "./features/dashboard/DashboardPage";
import { ItemsPage } from "./features/items/ItemsPage";
import { ReceiptsPage } from "./features/receipts/ReceiptsPage";
import { StockPage } from "./features/stock/StockPage";
import { archiveItem, confirmReceiptScan, createItem, createReceiptScan, createStockMovement, getCatalog, getDashboard, getInventory, getItems, getOcrHealth, getReceiptScans, retryReceiptScan, updateItem, updateReceiptLine, updateReceiptScan } from "./lib/api";
import type { Catalog, Dashboard, Item, ItemDraft, ReceiptScan, StockMovementDraft, ViewKey } from "./types";

const pageTitles: Record<ViewKey, string> = { overview: "Overview", items: "Items", stock: "Stock", receipts: "Receipts" };

export default function App() {
  const [activeView, setActiveView] = useState<ViewKey>("overview");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [inventory, setInventory] = useState<Item[]>([]);
  const [scans, setScans] = useState<ReceiptScan[]>([]);
  const [openItemForm, setOpenItemForm] = useState(false);
  const [openStockForm, setOpenStockForm] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const [nextDashboard, nextCatalog, nextItems, nextInventory, nextScans, nextOcrHealth] = await Promise.all([getDashboard(), getCatalog(), getItems(), getInventory(), getReceiptScans(), getOcrHealth()]);
    setDashboard({ ...nextDashboard, ocr: nextOcrHealth }); setCatalog(nextCatalog); setItems(nextItems); setInventory(nextInventory); setScans(nextScans);
  }, []);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try { await refresh(); } catch (cause) { setError(cause instanceof Error ? cause.message : "The inventory API is not reachable."); } finally { setLoading(false); }
  }, [refresh]);

  useEffect(() => { void load(); }, [load]);

  async function runMutation(action: () => Promise<unknown>) {
    setError(null);
    try { await action(); await refresh(); } catch (cause) { setError(cause instanceof Error ? cause.message : "The change could not be saved."); throw cause; }
  }

  async function handleCreateItem(draft: ItemDraft) { await runMutation(() => createItem(draft)); }
  async function handleUpdateItem(itemId: string, draft: Partial<ItemDraft>) { await runMutation(() => updateItem(itemId, draft)); }
  async function handleArchiveItem(itemId: string) { await runMutation(() => archiveItem(itemId)); }
  async function handleCreateMovement(draft: StockMovementDraft) { await runMutation(() => createStockMovement(draft)); }
  function upsertScan(scan: ReceiptScan) {
    setScans((current) => current.some((row) => row.id === scan.id)
      ? current.map((row) => row.id === scan.id ? scan : row)
      : [scan, ...current]);
  }
  async function handleCreateScan(file: File) { const scan = await createReceiptScan(file); upsertScan(scan); return scan; }
  async function handleRetryScan(scanId: string) { const scan = await retryReceiptScan(scanId); upsertScan(scan); return scan; }
  async function handleUpdateScan(scanId: string, payload: { purchased_at?: string | null }) { const scan = await updateReceiptScan(scanId, payload); upsertScan(scan); return scan; }
  async function handleUpdateLine(scanId: string, lineId: string, payload: { matched_item_id?: string | null; unit_id?: string | null; quantity?: string; unit_cost?: string; expiry_date?: string | null }) { const scan = await updateReceiptLine(scanId, lineId, payload); upsertScan(scan); return scan; }
  async function handleConfirmScan(scanId: string) { await runMutation(() => confirmReceiptScan(scanId)); }

  function navigate(view: ViewKey) {
    setActiveView(view);
    if (view !== "items") setOpenItemForm(false);
    if (view !== "stock") setOpenStockForm(false);
  }

  const page = useMemo(() => {
    if (!dashboard || !catalog) return <div className="loading-screen"><div className="loading-spinner" /><p>Preparing Maria’s inventory…</p></div>;
    if (activeView === "overview") return <DashboardPage dashboard={dashboard} onAddItem={() => { setOpenItemForm(true); setActiveView("items"); }} onReceiveStock={() => { setOpenStockForm(true); setActiveView("stock"); }} onScanReceipt={() => setActiveView("receipts")} onAddStock={() => { setOpenStockForm(true); setActiveView("stock"); }} onOpenItems={() => setActiveView("items")} onOpenStock={() => setActiveView("stock")} />;
    if (activeView === "items") return <ItemsPage items={items} catalog={catalog} initialOpen={openItemForm} onCreate={handleCreateItem} onUpdate={handleUpdateItem} onArchive={handleArchiveItem} />;
    if (activeView === "stock") return <StockPage items={inventory} movements={dashboard.recent_movements} initialOpen={openStockForm} onCreateMovement={handleCreateMovement} />;
    return <ReceiptsPage scans={scans} items={inventory} units={catalog.units} ocrHealth={dashboard.ocr} onCreateScan={handleCreateScan} onRetryScan={handleRetryScan} onUpdateScan={handleUpdateScan} onUpdateLine={handleUpdateLine} onConfirm={handleConfirmScan} />;
  }, [activeView, catalog, dashboard, inventory, items, scans]);

  return <AppShell activeView={activeView} onNavigate={navigate} pageTitle={pageTitles[activeView]} isLoading={loading && Boolean(dashboard)} error={error} onRetry={() => void load()}>{page}</AppShell>;
}
