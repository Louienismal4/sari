import { useMemo, useState } from "react";
import type { Catalog, Item, ItemDraft } from "../../types";
import { formatMoney, formatQuantity } from "../../lib/format";

interface ItemFormProps {
  catalog: Catalog;
  item?: Item | null;
  submitting?: boolean;
  onSubmit: (draft: ItemDraft) => void;
  onCancel: () => void;
}

function costPerSellingUnit(purchaseCost: string, conversion: string): number {
  const units = Number(conversion);
  return units > 0 ? Number((Number(purchaseCost || 0) / units).toFixed(2)) : 0;
}

function priceFromMarkup(cost: number, markup: string): string {
  return (cost * (1 + Number(markup || 0) / 100)).toFixed(2);
}

function markupFromPrice(cost: number, actualPrice: string): string {
  if (cost <= 0) return "0.00";
  return (((Number(actualPrice || 0) - cost) / cost) * 100).toFixed(2);
}

export function ItemForm({ catalog, item, submitting = false, onSubmit, onCancel }: ItemFormProps) {
  const initialConversion = item?.units_per_purchase_unit ?? "1";
  const initialPurchaseCost = item?.unit_cost ?? "0";
  const initialCostPerSellingUnit = costPerSellingUnit(initialPurchaseCost, initialConversion);
  const initialActualPrice = item?.actual_selling_price ?? priceFromMarkup(initialCostPerSellingUnit, "20");
  const [name, setName] = useState(item?.name ?? "");
  const [itemCode, setItemCode] = useState(item?.item_code ?? "");
  const [categoryId, setCategoryId] = useState(item?.category_id ?? catalog.categories[0]?.id ?? "");
  const [unitId, setUnitId] = useState(item?.unit_id ?? catalog.units[0]?.id ?? "");
  const [sellingUnitId, setSellingUnitId] = useState(item?.selling_unit_id ?? item?.unit_id ?? catalog.units[0]?.id ?? "");
  const [unitsPerPurchaseUnit, setUnitsPerPurchaseUnit] = useState(initialConversion);
  const [supplierId, setSupplierId] = useState(item?.primary_supplier_id ?? "");
  const [unitCost, setUnitCost] = useState(initialPurchaseCost);
  const [markup, setMarkup] = useState(item ? markupFromPrice(initialCostPerSellingUnit, initialActualPrice) : "20");
  const [actualPrice, setActualPrice] = useState(initialActualPrice);
  const [pricingBasis, setPricingBasis] = useState<"markup" | "actual">(item ? "actual" : "markup");
  const [reorderLevel, setReorderLevel] = useState(item?.reorder_level ?? "0");
  const [error, setError] = useState<string | null>(null);
  const purchaseUnit = useMemo(() => catalog.units.find((unit) => unit.id === unitId), [catalog.units, unitId]);
  const sellingUnit = useMemo(() => catalog.units.find((unit) => unit.id === sellingUnitId), [catalog.units, sellingUnitId]);
  const perUnitCost = useMemo(() => costPerSellingUnit(unitCost, unitsPerPurchaseUnit), [unitCost, unitsPerPurchaseUnit]);
  const profitPerSellingUnit = Number(actualPrice || 0) - perUnitCost;
  const sellingUnitsAvailable = (item ? Number(item.stock_on_hand) : 1) * Number(unitsPerPurchaseUnit || 0);
  const projectedProfit = profitPerSellingUnit * sellingUnitsAvailable;
  const grossMargin = Number(actualPrice || 0) > 0 ? (profitPerSellingUnit / Number(actualPrice)) * 100 : 0;

  function syncForCost(nextPurchaseCost: string, nextConversion: string) {
    const nextPerUnitCost = costPerSellingUnit(nextPurchaseCost, nextConversion);
    if (pricingBasis === "markup") setActualPrice(priceFromMarkup(nextPerUnitCost, markup));
    else setMarkup(markupFromPrice(nextPerUnitCost, actualPrice));
  }

  function updateMarkup(nextMarkup: string) {
    setPricingBasis("markup");
    setMarkup(nextMarkup);
    if (nextMarkup !== "") setActualPrice(priceFromMarkup(perUnitCost, nextMarkup));
  }

  function updateActualPrice(nextPrice: string) {
    setPricingBasis("actual");
    setActualPrice(nextPrice);
    if (nextPrice !== "") setMarkup(markupFromPrice(perUnitCost, nextPrice));
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim() || !categoryId || !unitId || !sellingUnitId) {
      setError("Name, category, purchase unit, and selling unit are required.");
      return;
    }
    if (!Number.isFinite(Number(unitsPerPurchaseUnit)) || Number(unitsPerPurchaseUnit) <= 0) {
      setError("Selling units per purchase unit must be greater than zero. For example: 40 pieces per box.");
      return;
    }
    if (!Number.isFinite(Number(markup)) || Number(markup) < -100) {
      setError("Markup cannot be lower than -100%.");
      return;
    }
    setError(null);
    onSubmit({ item_code: itemCode.trim() || undefined, name: name.trim(), category_id: categoryId, unit_id: unitId, selling_unit_id: sellingUnitId, units_per_purchase_unit: unitsPerPurchaseUnit, primary_supplier_id: supplierId || undefined, unit_cost: unitCost || "0", markup_percent: markup || "0", actual_selling_price: actualPrice || "0", reorder_level: reorderLevel || "0" });
  }

  return (
    <form className="form-stack" onSubmit={submit}>
      <div className="form-grid form-grid-two">
        <label className="form-field form-field-span"><span>Item name</span><input autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Cream-O Biscuits" /></label>
        <label className="form-field"><span>Item code <small>optional</small></span><input value={itemCode} onChange={(event) => setItemCode(event.target.value)} placeholder="Auto-generated" /></label>
        <label className="form-field"><span>Category</span><select value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>{catalog.categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
        <label className="form-field"><span>Purchase / stock unit</span><select value={unitId} onChange={(event) => { const nextUnitId = event.target.value; const wasOneToOne = sellingUnitId === unitId && Number(unitsPerPurchaseUnit) === 1; setUnitId(nextUnitId); if (wasOneToOne) setSellingUnitId(nextUnitId); }}>{catalog.units.map((unit) => <option key={unit.id} value={unit.id}>{unit.name} ({unit.abbreviation})</option>)}</select></label>
        <label className="form-field"><span>Sell by</span><select value={sellingUnitId} onChange={(event) => setSellingUnitId(event.target.value)}>{catalog.units.map((unit) => <option key={unit.id} value={unit.id}>{unit.name} ({unit.abbreviation})</option>)}</select></label>
        <label className="form-field form-field-span"><span>Selling units per purchase unit</span><input type="number" min="0.001" step="0.001" value={unitsPerPurchaseUnit} onChange={(event) => { const nextConversion = event.target.value; setUnitsPerPurchaseUnit(nextConversion); syncForCost(unitCost, nextConversion); }} /><small className="field-help">Example: 1 {purchaseUnit?.abbreviation ?? "box"} = {unitsPerPurchaseUnit || "0"} {sellingUnit?.abbreviation ?? "pc"}</small></label>
        <label className="form-field"><span>Primary supplier</span><select value={supplierId} onChange={(event) => setSupplierId(event.target.value)}><option value="">No supplier selected</option>{catalog.suppliers.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}</select></label>
        <label className="form-field"><span>Reorder level</span><input type="number" min="0" step="0.001" value={reorderLevel} onChange={(event) => setReorderLevel(event.target.value)} /></label>
      </div>
      <div className="form-divider" />
      <div className="form-grid form-grid-three">
        <label className="form-field"><span>Cost per {purchaseUnit?.abbreviation ?? "purchase unit"}</span><div className="input-prefix"><span>₱</span><input type="number" min="0" step="0.01" value={unitCost} onChange={(event) => { const nextCost = event.target.value; setUnitCost(nextCost); syncForCost(nextCost, unitsPerPurchaseUnit); }} /></div></label>
        <label className="form-field"><span>Markup per {sellingUnit?.abbreviation ?? "selling unit"}</span><div className="input-suffix"><input type="number" min="-100" step="0.01" value={markup} onChange={(event) => updateMarkup(event.target.value)} /><span>%</span></div></label>
        <label className="form-field"><span>Actual price per {sellingUnit?.abbreviation ?? "unit"}</span><div className="input-prefix"><span>₱</span><input type="number" min="0" step="0.01" value={actualPrice} onChange={(event) => updateActualPrice(event.target.value)} /></div></label>
      </div>
      <div className="price-preview"><span><strong>{formatMoney(perUnitCost)} cost per {sellingUnit?.abbreviation ?? "unit"}</strong><small>{formatMoney(unitCost || 0)} per {purchaseUnit?.abbreviation ?? "purchase unit"} ÷ {unitsPerPurchaseUnit || "0"}. Editing markup or actual price updates the other.</small></span><strong>{formatMoney(actualPrice || 0)} / {sellingUnit?.abbreviation ?? "unit"}</strong></div>
      <div className={`profit-preview ${profitPerSellingUnit < 0 ? "profit-preview-loss" : ""}`}><span><small>Profit per {sellingUnit?.abbreviation ?? "unit"}</small><strong>{formatMoney(profitPerSellingUnit)}</strong></span><span><small>Gross margin</small><strong>{grossMargin.toFixed(2)}%</strong></span><span><small>{item ? "Profit if all stock sells" : `Profit if one ${purchaseUnit?.abbreviation ?? "purchase unit"} sells`}</small><strong>{formatMoney(projectedProfit)}</strong><small>{formatQuantity(sellingUnitsAvailable)} {sellingUnit?.abbreviation ?? "units"}</small></span></div>
      {error ? <p className="form-error">{error}</p> : null}
      <div className="modal-actions"><button type="button" className="button button-secondary" onClick={onCancel}>Cancel</button><button type="submit" className="button button-primary" disabled={submitting}>{submitting ? "Saving…" : item ? "Save changes" : "Create item"}</button></div>
    </form>
  );
}
