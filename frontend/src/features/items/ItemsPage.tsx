import { useEffect, useMemo, useState } from "react";
import type { Catalog, Item, ItemDraft, Movement } from "../../types";
import { Icon } from "../../components/Icon";
import { Modal } from "../../components/Modal";
import { formatMoney, formatQuantity } from "../../lib/format";
import { getItemMovements } from "../../lib/api";
import { ItemForm } from "./ItemForm";

interface ItemsPageProps {
  items: Item[];
  catalog: Catalog;
  initialOpen?: boolean;
  onCreate: (draft: ItemDraft) => Promise<void>;
  onUpdate: (itemId: string, draft: Partial<ItemDraft>) => Promise<void>;
  onArchive: (itemId: string) => Promise<void>;
}

export function ItemsPage({ items, catalog, initialOpen = false, onCreate, onUpdate, onArchive }: ItemsPageProps) {
  const [query, setQuery] = useState("");
  const [lowStockOnly, setLowStockOnly] = useState(false);
  const [showCreate, setShowCreate] = useState(initialOpen);
  const [editingItem, setEditingItem] = useState<Item | null>(null);
  const [selectedItem, setSelectedItem] = useState<Item | null>(null);
  const [saving, setSaving] = useState(false);

  const filteredItems = useMemo(() => items.filter((item) => {
    const matchesQuery = !query.trim() || `${item.name} ${item.item_code}`.toLowerCase().includes(query.trim().toLowerCase());
    const matchesStock = !lowStockOnly || item.stock_status !== "healthy";
    return matchesQuery && matchesStock;
  }), [items, lowStockOnly, query]);

  async function handleCreate(draft: ItemDraft) {
    setSaving(true);
    try { await onCreate(draft); setShowCreate(false); } finally { setSaving(false); }
  }

  async function handleUpdate(draft: ItemDraft) {
    if (!editingItem) return;
    setSaving(true);
    try { await onUpdate(editingItem.id, draft); setEditingItem(null); } finally { setSaving(false); }
  }

  return (
    <div className="items-page">
      <section className="page-intro page-intro-compact">
        <div><h1>Items</h1><p>Keep your catalog, prices, and reorder levels in one place.</p></div>
        <button className="button button-primary" type="button" onClick={() => setShowCreate(true)}><Icon name="plus" size={19} />Add item</button>
      </section>
      <section className="toolbar">
        <label className="search-field"><Icon name="search" size={18} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search item name or code" aria-label="Search items" /></label>
        <button type="button" className={`filter-button ${lowStockOnly ? "filter-button-active" : ""}`} onClick={() => setLowStockOnly((value) => !value)}><Icon name="filter" size={17} />{lowStockOnly ? "Low stock only" : "All items"}</button>
        <span className="toolbar-count">{filteredItems.length} active {filteredItems.length === 1 ? "item" : "items"}</span>
      </section>
      <section className="table-panel">
        <div className="table-wrap items-table">
          <table>
            <thead><tr><th>Item</th><th>Category</th><th>Stock</th><th>Unit cost</th><th>Actual price</th><th>Status</th><th aria-label="Actions" /></tr></thead>
            <tbody>
              {filteredItems.map((item) => <tr key={item.id} onClick={() => setSelectedItem(item)}>
                <td><strong>{item.name}</strong><span className="table-secondary">{item.item_code}</span></td>
                <td>{item.category_name ?? "—"}</td>
                <td>{formatQuantity(item.stock_on_hand)} <span className="table-secondary">{item.unit_abbreviation}</span>{Number(item.units_per_purchase_unit) !== 1 || item.selling_unit_id !== item.unit_id ? <span className="table-secondary table-secondary-block">{formatQuantity(item.selling_units_on_hand)} {item.selling_unit_abbreviation}</span> : null}</td>
                <td>{formatMoney(item.unit_cost)}<span className="table-secondary table-secondary-block">per {item.unit_abbreviation}</span></td>
                <td>{formatMoney(item.actual_selling_price)}<span className="table-secondary table-secondary-block">per {item.selling_unit_abbreviation}</span></td>
                <td><span className={`status-text status-${item.stock_status}`}>{item.stock_status === "healthy" ? "Healthy" : item.stock_status === "out_of_stock" ? "Out of stock" : "Low stock"}</span></td>
                <td><button type="button" className="row-arrow" aria-label={`Open ${item.name}`} onClick={(event) => { event.stopPropagation(); setSelectedItem(item); }}><Icon name="chevron" size={18} /></button></td>
              </tr>)}
            </tbody>
          </table>
          {filteredItems.length === 0 ? <div className="empty-table">No items match this search.</div> : null}
        </div>
      </section>

      {showCreate ? <Modal title="Add item" description="Add a catalog item with its starting price rules." onClose={() => setShowCreate(false)}><ItemForm catalog={catalog} submitting={saving} onSubmit={handleCreate} onCancel={() => setShowCreate(false)} /></Modal> : null}
      {editingItem ? <Modal title="Edit item" description="Update catalog details without losing stock history." onClose={() => setEditingItem(null)}><ItemForm catalog={catalog} item={editingItem} submitting={saving} onSubmit={handleUpdate} onCancel={() => setEditingItem(null)} /></Modal> : null}
      {selectedItem ? <ItemDetail item={selectedItem} onClose={() => setSelectedItem(null)} onEdit={() => { setEditingItem(selectedItem); setSelectedItem(null); }} onArchive={async () => { await onArchive(selectedItem.id); setSelectedItem(null); }} /> : null}
    </div>
  );
}

function ItemDetail({ item, onClose, onEdit, onArchive }: { item: Item; onClose: () => void; onEdit: () => void; onArchive: () => Promise<void> }) {
  const [movements, setMovements] = useState<Movement[]>([]);
  const [archiving, setArchiving] = useState(false);
  useEffect(() => { getItemMovements(item.id).then(setMovements).catch(() => setMovements([])); }, [item.id]);
  async function archive() {
    setArchiving(true);
    try { await onArchive(); } finally { setArchiving(false); }
  }
  return <div className="drawer-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <aside className="detail-drawer" role="dialog" aria-modal="true" aria-labelledby="item-detail-title">
      <div className="drawer-header"><div><span className="field-label">{item.item_code}</span><h2 id="item-detail-title">{item.name}</h2></div><button className="icon-button" type="button" onClick={onClose} aria-label="Close item details"><Icon name="close" size={19} /></button></div>
      <div className="detail-balance"><span>Stock on hand</span><strong>{formatQuantity(item.stock_on_hand)} <small>{item.unit_abbreviation}</small></strong>{Number(item.units_per_purchase_unit) !== 1 || item.selling_unit_id !== item.unit_id ? <span className="detail-converted-stock">{formatQuantity(item.selling_units_on_hand)} {item.selling_unit_abbreviation} available</span> : null}<span className={`status-text status-${item.stock_status}`}>{item.stock_status === "healthy" ? "Healthy" : item.stock_status === "out_of_stock" ? "Out of stock" : "Low stock"}</span></div>
      <div className="detail-grid"><DetailStat label={`Cost / ${item.unit_abbreviation}`} value={formatMoney(item.unit_cost)} /><DetailStat label={`Cost / ${item.selling_unit_abbreviation}`} value={formatMoney(item.cost_per_selling_unit)} /><DetailStat label="Markup" value={`${item.markup_percent}%`} /><DetailStat label="Gross margin" value={`${item.gross_margin_percent}%`} /><DetailStat label={`Actual / ${item.selling_unit_abbreviation}`} value={formatMoney(item.actual_selling_price)} /><DetailStat label={`Profit / ${item.selling_unit_abbreviation}`} value={formatMoney(item.profit_per_selling_unit)} /><DetailStat label="Profit if all stock sells" value={formatMoney(item.projected_profit)} /><DetailStat label={`Reorder (${item.unit_abbreviation})`} value={formatQuantity(item.reorder_level)} /></div>
      <div className="detail-meta"><span>Packaging</span><strong>1 {item.unit_abbreviation} = {formatQuantity(item.units_per_purchase_unit)} {item.selling_unit_abbreviation}</strong><span>Category</span><strong>{item.category_name ?? "—"}</strong><span>Supplier</span><strong>{item.supplier_name ?? "No supplier"}</strong></div>
      <div className="drawer-section"><div className="section-heading"><h3>Movement history</h3><span className="table-secondary">{movements.length} records</span></div>{movements.length ? <div className="drawer-movements">{movements.slice(0, 8).map((movement) => <div className="drawer-movement" key={movement.id}><span>{movement.movement_type.replaceAll("_", " ")}</span><strong className={Number(movement.quantity_delta) >= 0 ? "amount-positive" : "amount-negative"}>{Number(movement.quantity_delta) >= 0 ? "+" : ""}{formatQuantity(movement.quantity_delta)}</strong></div>)}</div> : <p className="muted-copy">No movement history yet.</p>}</div>
      <div className="drawer-actions"><button type="button" className="button button-secondary" onClick={onEdit}><Icon name="edit" size={17} />Edit item</button><button type="button" className="button button-quiet-danger" onClick={archive} disabled={archiving}><Icon name="archive" size={17} />{archiving ? "Archiving…" : "Archive"}</button></div>
    </aside>
  </div>;
}

function DetailStat({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }
