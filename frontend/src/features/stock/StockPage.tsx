import { useMemo, useState } from "react";
import type { Item, Movement, StockMovementDraft } from "../../types";
import { Icon } from "../../components/Icon";
import { Modal } from "../../components/Modal";
import { formatDate, formatMoney, formatMovementLabel, formatQuantity, formatTime } from "../../lib/format";

interface StockPageProps {
  items: Item[];
  movements: Movement[];
  initialOpen?: boolean;
  onCreateMovement: (draft: StockMovementDraft) => Promise<void>;
}

export function StockPage({ items, movements, initialOpen = false, onCreateMovement }: StockPageProps) {
  const [showForm, setShowForm] = useState(initialOpen);
  const [selectedItemId, setSelectedItemId] = useState(items[0]?.id ?? "");
  const [movementType, setMovementType] = useState<StockMovementDraft["movement_type"]>("MANUAL_IN");
  const [quantity, setQuantity] = useState("1");
  const [quantityDelta, setQuantityDelta] = useState("");
  const [unitCost, setUnitCost] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectedItem = useMemo(() => items.find((item) => item.id === selectedItemId), [items, selectedItemId]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedItemId) {
      setError("Choose an item before recording a stock movement.");
      return;
    }
    if (!quantity || Number(quantity) <= 0) {
      setError(`Enter a quantity above zero${selectedItem?.unit_abbreviation ? ` in ${selectedItem.unit_abbreviation}` : ""}.`);
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      await onCreateMovement({ item_id: selectedItemId, movement_type: movementType, quantity, quantity_delta: movementType === "ADJUSTMENT" ? quantityDelta || quantity : undefined, unit_cost: unitCost || undefined, source: "manual", reference: movementType === "ADJUSTMENT" ? "Physical count" : undefined, notes: notes || undefined });
      setShowForm(false); setNotes(""); setQuantity("1"); setQuantityDelta("");
    } finally { setSubmitting(false); }
  }

  return <div className="stock-page">
    <section className="page-intro page-intro-compact"><div><h1>Stock</h1><p>Record every stock change and keep the ledger honest.</p></div><button className="button button-primary" type="button" onClick={() => setShowForm(true)}><Icon name="plus" size={19} />Record movement</button></section>
    <section className="stock-callout"><div><span className="field-label">Ledger rule</span><h2>Stock on hand is calculated from movements.</h2><p>Manual edits never overwrite history. Receipts, removals, and physical counts remain auditable.</p></div><span className="stock-callout-mark"><Icon name="clipboard" size={30} /></span></section>
    <section className="table-panel"><div className="panel-heading"><div><h2>Current inventory</h2><p>{items.length} active items</p></div><span className="panel-note">Values shown in purchase / stock units</span></div><div className="table-wrap"><table><thead><tr><th>Item</th><th>On hand</th><th>Reorder at</th><th>Purchase cost</th><th>Inventory value</th><th>Status</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td><strong>{item.name}</strong><span className="table-secondary">{item.item_code}</span></td><td>{formatQuantity(item.stock_on_hand)} {item.unit_abbreviation}{Number(item.units_per_purchase_unit) !== 1 || item.selling_unit_id !== item.unit_id ? <span className="table-secondary table-secondary-block">{formatQuantity(item.selling_units_on_hand)} {item.selling_unit_abbreviation}</span> : null}</td><td>{formatQuantity(item.reorder_level)} {item.unit_abbreviation}</td><td>{formatMoney(item.unit_cost)}<span className="table-secondary table-secondary-block">{formatMoney(item.cost_per_selling_unit)} / {item.selling_unit_abbreviation}</span></td><td>{formatMoney(Number(item.stock_on_hand) * Number(item.unit_cost))}</td><td><span className={`status-text status-${item.stock_status}`}>{item.stock_status === "healthy" ? "Healthy" : item.stock_status === "out_of_stock" ? "Out of stock" : "Low stock"}</span></td></tr>)}</tbody></table></div></section>
    <section className="content-section stock-history-section"><div className="section-heading"><h2>Movement history</h2><span className="table-secondary">Most recent first</span></div><div className="movement-list movement-list-wide">{movements.length ? movements.map((movement) => <div className="movement-row" key={movement.id}><span className={`movement-icon ${Number(movement.quantity_delta) >= 0 ? "movement-icon-positive" : "movement-icon-negative"}`}><Icon name={Number(movement.quantity_delta) >= 0 ? "arrow-down" : "arrow-up"} size={19} /></span><div className="movement-name"><strong>{formatMovementLabel(movement.movement_type)}</strong><span>{movement.item_name}</span></div><span className="movement-date">{formatDate(movement.created_at)} <span>{formatTime(movement.created_at)}</span></span><span className={Number(movement.quantity_delta) >= 0 ? "amount-positive" : "amount-negative"}>{Number(movement.quantity_delta) >= 0 ? "+" : ""}{formatQuantity(movement.quantity_delta)} units</span></div>) : <div className="empty-table">No movement history yet.</div>}</div></section>
    {showForm ? <Modal title="Record stock movement" description="Choose the movement type and quantity. The server will calculate the resulting balance." onClose={() => setShowForm(false)}><form className="form-stack" onSubmit={submit}><label className="form-field"><span>Item</span><select value={selectedItemId} onChange={(event) => setSelectedItemId(event.target.value)}>{items.map((item) => <option value={item.id} key={item.id}>{item.name} · {formatQuantity(item.stock_on_hand)} {item.unit_abbreviation} on hand</option>)}</select></label><div className="movement-choice-grid">{(["MANUAL_IN", "MANUAL_OUT", "ADJUSTMENT"] as const).map((type) => <button type="button" key={type} className={`movement-choice ${movementType === type ? "movement-choice-active" : ""}`} onClick={() => setMovementType(type)}><span>{type === "MANUAL_IN" ? "Stock in" : type === "MANUAL_OUT" ? "Stock out" : "Adjustment"}</span><small>{type === "MANUAL_IN" ? "Received or returned" : type === "MANUAL_OUT" ? "Damage, expiry, owner use" : "Physical count correction"}</small></button>)}</div><div className="form-grid form-grid-two"><label className="form-field"><span>{movementType === "ADJUSTMENT" ? "Quantity reference" : "Quantity"} ({selectedItem?.unit_abbreviation ?? "stock unit"})</span><input type="number" min="0.001" step="0.001" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></label>{movementType === "ADJUSTMENT" ? <label className="form-field"><span>Adjustment delta ({selectedItem?.unit_abbreviation ?? "stock unit"})</span><input type="number" step="0.001" value={quantityDelta} onChange={(event) => setQuantityDelta(event.target.value)} placeholder="+ or − from current" /></label> : <label className="form-field"><span>Cost per {selectedItem?.unit_abbreviation ?? "purchase unit"} <small>optional</small></span><div className="input-prefix"><span>₱</span><input type="number" min="0" step="0.01" value={unitCost} onChange={(event) => setUnitCost(event.target.value)} placeholder={selectedItem?.unit_cost ?? "0.00"} /></div></label>}</div><label className="form-field"><span>Notes <small>optional</small></span><textarea rows={3} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Add a reason or reference" /></label><div className="form-hint">{movementType === "ADJUSTMENT" ? `Use a positive or negative ${selectedItem?.unit_abbreviation ?? "stock-unit"} delta to correct the balance.` : movementType === "MANUAL_OUT" ? `Enter stock-out in ${selectedItem?.unit_abbreviation ?? "purchase units"}; the app also shows the equivalent ${selectedItem?.selling_unit_abbreviation ?? "selling units"}.` : `This movement is recorded in ${selectedItem?.unit_abbreviation ?? "purchase units"}.`}</div>{error ? <p className="form-error" role="alert">{error}</p> : null}<div className="modal-actions"><button type="button" className="button button-secondary" onClick={() => setShowForm(false)}>Cancel</button><button type="submit" className="button button-primary" disabled={submitting}>{submitting ? "Recording…" : "Record movement"}</button></div></form></Modal> : null}
  </div>;
}
