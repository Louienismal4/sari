import { useEffect, useMemo, useState } from "react";
import type { CatalogUnit, Item, OCRHealth, ReceiptScan } from "../../types";
import { Icon } from "../../components/Icon";
import { formatDate, formatMoney } from "../../lib/format";
import { CameraCapture } from "./CameraCapture";

type ReceiptScanUpdate = { purchased_at?: string | null };
type ReceiptLineUpdate = { matched_item_id?: string | null; unit_id?: string | null; quantity?: string; unit_cost?: string; expiry_date?: string | null };
type Notice = { kind: "error" | "success" | "info"; text: string };

interface ReceiptsPageProps {
  scans: ReceiptScan[];
  items: Item[];
  units: CatalogUnit[];
  ocrHealth: OCRHealth;
  onCreateScan: (file?: File) => Promise<ReceiptScan>;
  onRetryScan: (scanId: string) => Promise<ReceiptScan>;
  onUpdateScan: (scanId: string, payload: ReceiptScanUpdate) => Promise<ReceiptScan>;
  onUpdateLine: (scanId: string, lineId: string, payload: ReceiptLineUpdate) => Promise<ReceiptScan>;
  onConfirm: (scanId: string) => Promise<void>;
}

export function ReceiptsPage({ scans, items, units, ocrHealth, onCreateScan, onRetryScan, onUpdateScan, onUpdateLine, onConfirm }: ReceiptsPageProps) {
  const [activeScan, setActiveScan] = useState<ReceiptScan | null>(scans[0] ?? null);
  const [workflowBusy, setWorkflowBusy] = useState(false);
  const [savingLineId, setSavingLineId] = useState<string | null>(null);
  const [savingScan, setSavingScan] = useState(false);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  useEffect(() => {
    setActiveScan((current) => current ? scans.find((scan) => scan.id === current.id) ?? current : scans[0] ?? null);
  }, [scans]);

  const confirmationBlocker = useMemo(() => getConfirmationBlocker(activeScan), [activeScan]);

  function showError(error: unknown, fallback: string) {
    setNotice({ kind: "error", text: error instanceof Error ? error.message : fallback });
  }

  async function create(file?: File) {
    setWorkflowBusy(true); setNotice(null);
    try {
      setActiveScan(await onCreateScan(file));
      setNotice({ kind: "success", text: "Receipt draft ready. Review every line before confirming." });
    } catch (error) {
      showError(error, "Receipt could not be uploaded. Choose a JPG, PNG, or WEBP image under 10 MB and try again.");
    } finally { setWorkflowBusy(false); }
  }

  async function retry(scanId: string) {
    setWorkflowBusy(true); setNotice(null);
    try {
      setActiveScan(await onRetryScan(scanId));
      setNotice({ kind: "success", text: "OCR retry finished. Review the new draft before confirming." });
    } catch (error) {
      showError(error, "OCR retry could not be started. Check the OCR gateway status, then try again.");
    } finally { setWorkflowBusy(false); }
  }

  async function updateLine(lineId: string, payload: ReceiptLineUpdate) {
    if (!activeScan) {
      setNotice({ kind: "error", text: "Select a receipt before editing a line." });
      return;
    }
    setSavingLineId(lineId);
    try { setActiveScan(await onUpdateLine(activeScan.id, lineId, payload)); }
    catch (error) { showError(error, "Line could not be updated. Check the value and try again."); }
    finally { setSavingLineId(null); }
  }

  async function updateScan(payload: ReceiptScanUpdate) {
    if (!activeScan) {
      setNotice({ kind: "error", text: "Select a receipt before changing its purchase date." });
      return;
    }
    setSavingScan(true);
    try { setActiveScan(await onUpdateScan(activeScan.id, payload)); }
    catch (error) { showError(error, "Receipt could not be updated. Check the date and try again."); }
    finally { setSavingScan(false); }
  }

  async function confirm() {
    if (confirmationBlocker) {
      setNotice({ kind: "error", text: confirmationBlocker });
      return;
    }
    if (!activeScan) return;
    setWorkflowBusy(true); setNotice(null);
    try {
      await onConfirm(activeScan.id);
      setActiveScan((current) => current ? { ...current, status: "CONFIRMED" } : current);
      setNotice({ kind: "success", text: "Receipt confirmed. New items were created where needed and stock was posted once." });
    } catch (error) { showError(error, "Receipt could not be confirmed. Review the highlighted requirements and try again."); }
    finally { setWorkflowBusy(false); }
  }

  function handleCaptured(file: File) {
    setCameraOpen(false);
    void create(file);
  }

  return <div className="receipts-page">
    <section className="page-intro page-intro-compact">
      <div><h1>Receipts</h1><p>Turn supplier receipts into reviewable stock drafts.</p></div>
      <div className="receipt-capture-actions">
        <button type="button" className="button button-primary" onClick={() => setCameraOpen(true)} disabled={workflowBusy}><Icon name="camera" size={19} />Use camera</button>
        <FileUploadButton onFile={(file) => void create(file)} disabled={workflowBusy} />
      </div>
    </section>
    <div className="receipt-layout">
      <section className="receipt-workspace">
        {!activeScan ? <ReceiptStart busy={workflowBusy} onCamera={() => setCameraOpen(true)} onFile={(file) => void create(file)} onSample={() => void create()} /> : <ReceiptReview scan={activeScan} items={items} units={units} busy={workflowBusy} savingLineId={savingLineId} savingScan={savingScan} confirmationBlocker={confirmationBlocker} onInvalid={(text) => setNotice({ kind: "error", text })} onUpdateScan={updateScan} onUpdateLine={updateLine} onRetry={() => void retry(activeScan.id)} onConfirm={confirm} />}
        {notice ? <div className={`receipt-message receipt-message-${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}><Icon name={notice.kind === "success" ? "check" : notice.kind === "error" ? "alert" : "refresh"} size={17} />{notice.text}</div> : null}
      </section>
      <aside className="receipt-history">
        <div className="section-heading"><h2>Recent scans</h2><span className="table-secondary">{scans.length}</span></div>
        {scans.length ? scans.map((scan) => <button type="button" className={`scan-history-row ${activeScan?.id === scan.id ? "scan-history-row-active" : ""}`} key={scan.id} onClick={() => { setActiveScan(scan); setNotice(null); }}><span className={`scan-status-dot scan-status-${scan.status.toLowerCase()}`} /><span><strong>{scan.merchant_name ?? "Supplier receipt"}</strong><small>{formatDate(scan.created_at)} · {scan.lines.length} lines</small></span><span className="table-secondary">{scanStatusLabel(scan.status)}</span></button>) : <p className="muted-copy">No receipt scans yet.</p>}
        <div className="ocr-note"><span className={`status-dot ${ocrHealth.status === "online" ? "status-dot-online" : "status-dot-offline"}`} /><div><strong>OCR gateway {ocrHealth.status === "online" ? "online" : "offline"}</strong><p>{ocrHealth.provider} · {ocrHealth.message}</p></div></div>
      </aside>
    </div>
    {cameraOpen ? <CameraCapture onCapture={handleCaptured} onClose={() => setCameraOpen(false)} /> : null}
  </div>;
}

function FileUploadButton({ onFile, disabled = false }: { onFile: (file: File) => void; disabled?: boolean }) {
  return <label className={`button button-secondary upload-button ${disabled ? "button-disabled" : ""}`}><Icon name="upload" size={18} />Upload file<input type="file" accept="image/jpeg,image/png,image/webp" disabled={disabled} onChange={(event) => { const file = event.target.files?.[0]; if (file) onFile(file); event.currentTarget.value = ""; }} /></label>;
}

function ReceiptStart({ busy, onCamera, onFile, onSample }: { busy: boolean; onCamera: () => void; onFile: (file: File) => void; onSample: () => void }) {
  return <div className="receipt-start"><div className="receipt-start-icon"><Icon name="receipt" size={42} /></div><h2>Start with a supplier receipt</h2><p>Use your phone camera or upload an image. OCR only creates a draft—nothing changes in stock until you confirm it.</p><div className="receipt-start-actions"><button type="button" className="button button-primary" onClick={onCamera} disabled={busy}><Icon name="camera" size={18} />Capture receipt</button><FileUploadButton onFile={onFile} disabled={busy} /><button type="button" className="button button-quiet-danger" onClick={onSample} disabled={busy}>Use sample receipt</button></div></div>;
}

function scanStatusLabel(status: ReceiptScan["status"]): string {
  if (status === "CONFIRMED") return "Done";
  if (status === "REVIEW") return "Review";
  if (status === "PROCESSING") return "Scanning";
  if (status === "WAITING_FOR_SERVICE") return "Waiting";
  if (status === "FAILED") return "Failed";
  return "Draft";
}

function scanErrorTitle(scan: ReceiptScan): string {
  if (scan.status !== "WAITING_FOR_SERVICE") return "Receipt OCR needs attention";
  if (scan.gateway_error_code === "provider_timeout") return "OCR gateway timed out";
  if (scan.gateway_error_code === "provider_initialization") return "OCR gateway is warming up";
  return "OCR gateway is offline";
}

function dateInputValue(value: string | null): string {
  return value ? value.slice(0, 10) : "";
}

function sanitizeDecimalInput(value: string, maxFractionDigits: number): string {
  const cleaned = value.replace(/[^\d.]/g, "");
  const [whole, ...fractionParts] = cleaned.split(".");
  if (!fractionParts.length) return whole;
  return `${whole}.${fractionParts.join("").slice(0, maxFractionDigits)}`;
}

function getConfirmationBlocker(scan: ReceiptScan | null): string | null {
  if (!scan) return "Upload or capture a receipt before posting stock.";
  if (scan.status === "CONFIRMED") return "This receipt has already been posted.";
  if (scan.status === "PROCESSING") return "Wait for OCR to finish before posting stock.";
  if (scan.status === "WAITING_FOR_SERVICE" || scan.status === "FAILED") return "Retry OCR and wait for a review draft before posting stock.";
  if (scan.status !== "REVIEW") return "This receipt is not ready to post yet.";
  if (!scan.lines.length) return "No receipt lines were detected. Retry OCR with a clearer image before posting stock.";
  const missingUnits = scan.lines.filter((line) => !line.unit_id).map((line) => line.name);
  if (missingUnits.length) return `Choose a unit for ${missingUnits.join(", ")}. Unmatched lines will be created as new inventory items.`;
  const invalidQuantity = scan.lines.find((line) => !Number.isFinite(Number(line.quantity)) || Number(line.quantity) <= 0);
  if (invalidQuantity) return `Enter a quantity above zero for ${invalidQuantity.name}.`;
  const invalidCost = scan.lines.find((line) => !Number.isFinite(Number(line.unit_cost)) || Number(line.unit_cost) < 0);
  if (invalidCost) return `Enter a valid unit cost for ${invalidCost.name}.`;
  return null;
}

function NumericTextField({ value, min, maxFractionDigits, disabled, ariaLabel, onCommit, onInvalid }: { value: string; min: number; maxFractionDigits: number; disabled: boolean; ariaLabel: string; onCommit: (value: string) => Promise<void>; onInvalid: (message: string) => void }) {
  const [draft, setDraft] = useState(value);

  useEffect(() => { setDraft(value); }, [value]);

  function commit() {
    const parsed = Number(draft);
    if (!draft || !Number.isFinite(parsed) || parsed < min) {
      onInvalid(`${ariaLabel} must be ${min === 0 ? "zero or higher" : `at least ${min}`}.`);
      setDraft(value);
      return;
    }
    if (draft !== value) void onCommit(draft);
  }

  return <input
    type="text"
    inputMode="decimal"
    pattern={"[0-9]*\\.?[0-9]*"}
    value={draft}
    onChange={(event) => setDraft(sanitizeDecimalInput(event.currentTarget.value, maxFractionDigits))}
    onBlur={commit}
    onKeyDown={(event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        event.currentTarget.blur();
      }
    }}
    aria-label={ariaLabel}
    disabled={disabled}
  />;
}

function DateField({ value, disabled, ariaLabel, onCommit }: { value: string; disabled: boolean; ariaLabel: string; onCommit: (value: string | null) => Promise<void> }) {
  const [draft, setDraft] = useState(value);

  useEffect(() => { setDraft(value); }, [value]);

  function commit(nextValue: string) {
    if (nextValue !== value) void onCommit(nextValue || null);
  }

  return <input
    type="date"
    aria-label={ariaLabel}
    value={draft}
    onChange={(event) => setDraft(event.currentTarget.value)}
    onBlur={(event) => commit(event.currentTarget.value)}
    disabled={disabled}
  />;
}

function ReceiptReview({ scan, items, units, busy, savingLineId, savingScan, confirmationBlocker, onInvalid, onUpdateScan, onUpdateLine, onRetry, onConfirm }: { scan: ReceiptScan; items: Item[]; units: CatalogUnit[]; busy: boolean; savingLineId: string | null; savingScan: boolean; confirmationBlocker: string | null; onInvalid: (message: string) => void; onUpdateScan: (payload: ReceiptScanUpdate) => Promise<void>; onUpdateLine: (lineId: string, payload: ReceiptLineUpdate) => Promise<void>; onRetry: () => void; onConfirm: () => Promise<void> }) {
  const isConfirmed = scan.status === "CONFIRMED";
  const hasError = Boolean(scan.error) || scan.status === "WAITING_FOR_SERVICE" || scan.status === "FAILED";
  return <div className="receipt-review">
    <div className="receipt-review-header"><div><span className="field-label">{scan.receipt_number ?? "Draft receipt"}</span><h2>{scan.merchant_name ?? "Supplier receipt"}</h2><p>{formatDate(scan.purchased_at)} · {scan.original_filename}</p></div><div className="receipt-review-header-actions"><label className="receipt-date-field"><span className="field-label">Date of purchase (DOP)</span><DateField ariaLabel="Date of purchase" value={dateInputValue(scan.purchased_at)} onCommit={(value) => onUpdateScan({ purchased_at: value ? `${value}T00:00:00` : null })} disabled={busy || savingScan || isConfirmed} /></label><span className={`review-state review-state-${scan.status.toLowerCase()}`}>{scanStatusLabel(scan.status)}</span></div></div>
    <div className="receipt-summary"><div><span>Detected total</span><strong>{formatMoney(scan.total)}</strong></div><div><span>Provider</span><strong>{scan.provider}</strong></div><div><span>Lines</span><strong>{scan.lines.length}</strong></div><div><span>Attempts</span><strong>{scan.attempt_count}</strong></div></div>
    {hasError ? <div className="review-error" role="alert"><div><strong>{scanErrorTitle(scan)}</strong><p>{scan.error ?? "The draft is saved and can be retried when the service is available."}</p></div>{scan.can_retry ? <button type="button" className="button button-secondary" disabled={busy} onClick={onRetry}><Icon name="refresh" size={17} />Retry OCR</button> : null}</div> : null}
    {scan.warnings?.length ? <div className="review-warning"><Icon name="scan" size={18} /><span>{scan.warnings[0]}</span></div> : <div className="review-warning"><Icon name="scan" size={18} /><span>OCR results are drafts. Correct names, quantities, and costs before posting stock.</span></div>}
    <div className="receipt-lines">
      <div className="receipt-line-header"><span>Detected line</span><span>Match to item</span><span>Qty</span><span>Unit</span><span>Unit cost</span></div>
      {scan.lines.length ? scan.lines.map((line) => {
        const lineBusy = busy || savingLineId === line.id || isConfirmed;
        return <div className={`receipt-line ${!line.matched_item_id && !line.unit_id ? "receipt-line-needs-unit" : ""}`} key={line.id}>
          <div><strong>{line.name}</strong><small>{line.raw_text}</small></div>
          <label className="receipt-item-match">
            <select aria-label={`Inventory item for ${line.name}`} value={line.matched_item_id ?? "__new__"} onChange={(event) => { const selectedItem = items.find((item) => item.id === event.target.value); void onUpdateLine(line.id, selectedItem ? { matched_item_id: selectedItem.id, unit_id: selectedItem.unit_id } : { matched_item_id: null, unit_id: line.unit_id }); }} disabled={lineBusy}>
              <option value="__new__">Create “{line.name}” as new</option>
              {items.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}
            </select>
            {!line.matched_item_id ? <small className="receipt-new-item-note">Creates a new item when stock is posted</small> : null}
          </label>
          <NumericTextField value={line.quantity} min={0.001} maxFractionDigits={3} ariaLabel={`Quantity for ${line.name}`} onCommit={(value) => onUpdateLine(line.id, { quantity: value })} onInvalid={onInvalid} disabled={lineBusy} />
          <select aria-label={`Unit for ${line.name}`} value={line.unit_id ?? ""} onChange={(event) => void onUpdateLine(line.id, { unit_id: event.target.value || null })} disabled={lineBusy}><option value="">Select unit</option>{units.map((unit) => <option value={unit.id} key={unit.id}>{unit.abbreviation} · {unit.name}</option>)}</select>
          <div className="line-money"><span>₱</span><NumericTextField value={line.unit_cost} min={0} maxFractionDigits={2} ariaLabel={`Unit cost for ${line.name}`} onCommit={(value) => onUpdateLine(line.id, { unit_cost: value })} onInvalid={onInvalid} disabled={lineBusy} /></div>
          <label className="receipt-line-expiry"><span>Expiry date</span><DateField ariaLabel={`Expiry date for ${line.name}`} value={line.expiry_date ?? ""} onCommit={(value) => onUpdateLine(line.id, { expiry_date: value })} disabled={lineBusy} /></label>
        </div>;
      }) : <div className="receipt-lines-empty">No structured lines are available yet. Retry OCR or enter this receipt through Stock.</div>}
    </div>
    <div className="receipt-total-row"><span>Review total</span><strong>{formatMoney(scan.lines.reduce((sum, line) => sum + Number(line.line_total), 0))}</strong></div>
    <div className="modal-actions"><button type="button" className="button button-secondary" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}>Keep editing</button><button type="button" className="button button-primary" disabled={busy || isConfirmed} title={confirmationBlocker ?? undefined} onClick={() => void onConfirm()}><Icon name="check" size={18} />{isConfirmed ? "Confirmed" : busy ? "Posting…" : "Confirm & post stock"}</button></div>
  </div>;
}
