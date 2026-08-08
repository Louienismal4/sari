import type { Dashboard, Item, Movement } from "../../types";
import { Icon } from "../../components/Icon";
import { formatDate, formatMoney, formatMovementLabel, formatQuantity, formatTime, isPositiveMovement } from "../../lib/format";

interface DashboardPageProps {
  dashboard: Dashboard;
  onAddItem: () => void;
  onReceiveStock: () => void;
  onScanReceipt: () => void;
  onAddStock: () => void;
  onOpenItems: () => void;
  onOpenStock: () => void;
}

export function DashboardPage({ dashboard, onAddItem, onReceiveStock, onScanReceipt, onAddStock, onOpenItems, onOpenStock }: DashboardPageProps) {
  const { metrics, low_stock_items: lowStockItems, recent_movements: recentMovements, ocr } = dashboard;
  return (
    <div className="dashboard-page">
      <section className="page-intro">
        <div>
          <h1>Good morning, Maria</h1>
          <p>Here’s the stock picture for today.</p>
        </div>
        <div className="page-actions">
          <button className="button button-primary" type="button" onClick={onAddItem}><Icon name="plus" size={19} />Add item</button>
          <button className="button button-secondary" type="button" onClick={onReceiveStock}><Icon name="receive" size={19} />Receive stock</button>
        </div>
      </section>

      <section className="metrics-strip" aria-label="Inventory summary">
        <Metric label="Active items" value={String(metrics.active_items)} />
        <Metric label="Units on hand" value={formatQuantity(metrics.units_on_hand)} />
        <Metric label="Inventory value" value={formatMoney(metrics.inventory_value)} />
        <Metric label="Low stock" value={String(metrics.low_stock)} tone={metrics.low_stock > 0 ? "alert" : "normal"} />
      </section>

      <div className="dashboard-grid">
        <div className="dashboard-main-column">
          <section className="content-section">
            <SectionHeading title="Needs attention" actionLabel="View all items" onAction={onOpenItems} />
            <AttentionTable items={lowStockItems} />
          </section>
          <section className="content-section">
            <SectionHeading title="Recent movement" actionLabel="View stock" onAction={onOpenStock} />
            <MovementList movements={recentMovements} />
          </section>
        </div>

        <aside className="quick-actions-panel">
          <h2>Quick actions</h2>
          <button type="button" className="quick-action" onClick={onScanReceipt}>
            <span className="quick-action-icon"><Icon name="scan" size={25} /></span>
            <span>Scan supplier<br />receipt</span>
            <Icon name="chevron" size={19} />
          </button>
          <button type="button" className="quick-action" onClick={onAddStock}>
            <span className="quick-action-icon"><Icon name="box" size={25} /></span>
            <span>Add stock<br />manually</span>
            <Icon name="chevron" size={19} />
          </button>
          <div className="receipt-empty-state">
            <div className="receipt-empty-icon"><Icon name="receipt" size={34} /></div>
            <h3>No receipt scanned yet</h3>
            <p>Scan a supplier receipt to capture items and quantities.</p>
          </div>
          <div className="ocr-status"><span className={`status-dot ${ocr.status === "online" ? "status-dot-online" : "status-dot-offline"}`} />{ocr.provider === "mock" ? "OCR gateway online · mock" : "OCR gateway online"}</div>
        </aside>
      </div>
    </div>
  );
}

function Metric({ label, value, tone = "normal" }: { label: string; value: string; tone?: "normal" | "alert" }) {
  return <div className="metric"><span className="metric-label">{label}</span><strong className={tone === "alert" ? "text-alert" : ""}>{value}</strong></div>;
}

function SectionHeading({ title, actionLabel, onAction }: { title: string; actionLabel: string; onAction: () => void }) {
  return <div className="section-heading"><h2>{title}</h2><button type="button" className="text-button" onClick={onAction}>{actionLabel}<Icon name="chevron" size={15} /></button></div>;
}

function AttentionTable({ items }: { items: Item[] }) {
  if (items.length === 0) return <div className="empty-table">All active items are above their reorder level.</div>;
  return (
    <div className="table-wrap attention-table">
      <table>
        <thead><tr><th>Item</th><th>Stock</th><th>Reorder at</th><th>Status</th><th aria-label="Open item" /></tr></thead>
        <tbody>
          {items.map((item) => <tr key={item.id}>
            <td><strong>{item.name}</strong><span className="table-secondary">{item.item_code}</span></td>
            <td>{formatQuantity(item.stock_on_hand)} <span className="table-secondary">{item.unit_abbreviation}</span></td>
            <td>{formatQuantity(item.reorder_level)}</td>
            <td><span className={`status-text ${item.stock_status === "out_of_stock" ? "status-out" : "status-low"}`}>{item.stock_status === "out_of_stock" ? "Out of stock" : "Low stock"}</span></td>
            <td><button type="button" className="row-arrow" aria-label={`Open ${item.name}`}><Icon name="chevron" size={18} /></button></td>
          </tr>)}
        </tbody>
      </table>
    </div>
  );
}

export function MovementList({ movements }: { movements: Movement[] }) {
  if (movements.length === 0) return <div className="empty-table">No movement has been recorded yet.</div>;
  return (
    <div className="movement-list">
      {movements.map((movement) => {
        const positive = isPositiveMovement(movement.movement_type, movement.quantity_delta);
        return <div className="movement-row" key={movement.id}>
          <span className={`movement-icon ${positive ? "movement-icon-positive" : movement.movement_type === "ADJUSTMENT" ? "movement-icon-neutral" : "movement-icon-negative"}`}><Icon name={movement.movement_type === "ADJUSTMENT" ? "clipboard" : positive ? "arrow-down" : "arrow-up"} size={20} /></span>
          <div className="movement-name"><strong>{formatMovementLabel(movement.movement_type)}</strong><span>{movement.item_name ?? "Inventory"}</span></div>
          <span className="movement-date">{formatDate(movement.created_at)} <span>{formatTime(movement.created_at)}</span></span>
          <span className={`movement-amount ${positive ? "amount-positive" : "amount-negative"}`}>{positive ? "+" : ""}{formatQuantity(movement.quantity_delta)} units</span>
          <Icon name="chevron" size={17} />
        </div>;
      })}
    </div>
  );
}

