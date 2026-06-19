import { Component, computed, input } from '@angular/core';

import { MetricValue } from '../core/models';

// `<energy-flow>` (plan.md §8): the Now-view centrepiece — a five-node topology diagram of
// where energy is moving right now. Inverter centre; solar top-left, house top-right, battery
// bottom-left, grid bottom-right; each corner wired to the inverter. Node rings are coloured by
// per-node status (green/red/grey) and each active edge carries chevrons travelling in the
// energy-flow direction. Pure presentational + dumb: it takes the normalized metric snapshot and
// the inverter-online flag, nothing else — so it drops straight into the L06 widget registry.
//
// Colours map to Bootstrap semantic roles (theme-aware via CSS variables, no redraw on theme
// switch). The metric→{ring colour, flow direction} mapping is the gnarly bit and lives in the
// pure `computeEnergyFlow()` below so it can be unit-tested without a DOM (plan.md §21).

/** Bootstrap semantic role driving a node ring / flow colour: green / red / grey. */
export type FlowRole = 'success' | 'danger' | 'secondary';
export type EdgeId = 'solar' | 'house' | 'battery' | 'grid';

export interface FlowEdge {
  id: EdgeId;
  /** Is energy actually moving on this edge right now? */
  active: boolean;
  /** Direction of flow: true = corner→inverter, false = inverter→corner. */
  toInverter: boolean;
  /** Colour of the flow on this edge (the corner node's status; grey for the house leg). */
  role: FlowRole;
}

export interface EnergyFlowModel {
  solar: FlowRole;
  house: FlowRole;
  battery: FlowRole;
  grid: FlowRole;
  inverter: FlowRole;
  edges: FlowEdge[];
}

/** Below this many watts a flow reads as idle (matches the Now gauges' threshold). */
const IDLE_W = 1;

function num(v: MetricValue | undefined): number | undefined {
  return typeof v === 'number' ? v : undefined;
}

/**
 * Pure metric → flow model. Signs follow the canonical vocabulary (plan.md §4) and are NEVER
 * re-derived in the UI: `battery_power_w` +charge/−discharge, `grid_power_w` +import/−export.
 *
 * - Solar  — green producing (`pv_power_w > 0`), grey idle.
 * - Battery— green charging, red discharging, grey idle.
 * - Grid   — green exporting, red importing, grey idle.
 * - House  — always grey (a sink; colour carries no directional meaning).
 * - Inverter — green online, red fault/offline.
 *
 * Flow colour is the corner node's own status (so it reads "green toward a charging battery,
 * red away from a discharging one"); the house leg is grey (neutral delivery). When the inverter
 * is offline nothing flows.
 */
export function computeEnergyFlow(
  metrics: Record<string, MetricValue> | null | undefined,
  inverterOnline: boolean,
): EnergyFlowModel {
  const m = metrics ?? {};
  const pv = num(m['pv_power_w']);
  const batt = num(m['battery_power_w']); // + charge, − discharge
  const grid = num(m['grid_power_w']); //    + import, − export
  const load = num(m['load_power_w']);

  const producing = (pv ?? 0) > IDLE_W;
  const solar: FlowRole = producing ? 'success' : 'secondary';

  let battery: FlowRole = 'secondary';
  const battActive = batt !== undefined && Math.abs(batt) > IDLE_W;
  if (battActive) battery = batt! > 0 ? 'success' : 'danger';

  let grid_: FlowRole = 'secondary';
  const gridActive = grid !== undefined && Math.abs(grid) > IDLE_W;
  if (gridActive) grid_ = grid! > 0 ? 'danger' : 'success';

  const inverter: FlowRole = inverterOnline ? 'success' : 'danger';
  const house: FlowRole = 'secondary';

  const edges: FlowEdge[] = [
    { id: 'solar', active: inverterOnline && producing, toInverter: true, role: solar },
    { id: 'house', active: inverterOnline && (load ?? 0) > IDLE_W, toInverter: false, role: house },
    // Discharging (batt<0) flows battery→inverter; charging (batt>0) flows inverter→battery.
    { id: 'battery', active: inverterOnline && battActive, toInverter: (batt ?? 0) < 0, role: battery },
    // Importing (grid>0) flows grid→inverter; exporting (grid<0) flows inverter→grid.
    { id: 'grid', active: inverterOnline && gridActive, toInverter: (grid ?? 0) > 0, role: grid_ },
  ];

  return { solar, house, battery, grid: grid_, inverter, edges };
}

// ── Geometry (a 0–100 viewBox the square container maps 1:1 to its CSS percentages) ──
const INV = { x: 50, y: 50, r: 13 };
const CORNER_R = 11;
const CORNERS: Record<EdgeId, { x: number; y: number; icon: string; name: string }> = {
  solar: { x: 20, y: 20, icon: 'bi-sun-fill', name: 'Solar' },
  house: { x: 80, y: 20, icon: 'bi-house-fill', name: 'House' },
  battery: { x: 20, y: 80, icon: 'bi-battery-half', name: 'Battery' },
  grid: { x: 80, y: 80, icon: 'bi-plug-fill', name: 'Grid' },
};

interface RenderEdge {
  id: EdgeId;
  active: boolean;
  role: FlowRole;
  x1: number; y1: number; x2: number; y2: number; // dim "wire" (constant, edge-to-edge)
  path: string; // offset-path for the flow chevrons (from→to in the energy direction)
}

/** Trim a corner→inverter segment to the two circle edges and resolve the flow direction. */
function renderEdge(e: FlowEdge): RenderEdge {
  const c = CORNERS[e.id];
  const dx = INV.x - c.x;
  const dy = INV.y - c.y;
  const len = Math.hypot(dx, dy);
  const ux = dx / len;
  const uy = dy / len;
  const round = (n: number) => Math.round(n * 100) / 100;
  const cEdge = { x: round(c.x + CORNER_R * ux), y: round(c.y + CORNER_R * uy) };
  const iEdge = { x: round(INV.x - INV.r * ux), y: round(INV.y - INV.r * uy) };

  // Chevrons ride an offset-path from→to in the energy direction (offset-rotate:auto aligns
  // them to the tangent, so no manual angle needed); reverse the path for inverter→corner flow.
  const from = e.toInverter ? cEdge : iEdge;
  const to = e.toInverter ? iEdge : cEdge;
  // Raw style attribute (set via [attr.style] — Angular's per-property style bindings silently
  // drop offset-path / custom props on these SVG <path> nodes).
  const path = `offset-path:path('M ${from.x} ${from.y} L ${to.x} ${to.y}')`;

  return { id: e.id, active: e.active, role: e.role, x1: cEdge.x, y1: cEdge.y, x2: iEdge.x, y2: iEdge.y, path };
}

@Component({
  selector: 'app-energy-flow',
  template: `
    <div class="ef-widget" role="img" [attr.aria-label]="ariaLabel()">
      <svg class="ef-svg" viewBox="0 0 100 100" aria-hidden="true">
        <!-- Connector wires (all four, dim) -->
        @for (e of edges(); track e.id) {
          <line class="ef-wire" [attr.x1]="e.x1" [attr.y1]="e.y1" [attr.x2]="e.x2" [attr.y2]="e.y2" />
        }
        <!-- Flow on active edges: a tinted "lit" wire (always) + chevrons travelling from→to;
             under reduced motion the chevrons give way to a single static arrowhead (CSS chooses). -->
        @for (e of edges(); track e.id) {
          @if (e.active) {
            <g class="ef-edge" [attr.data-edge]="e.id" [style.color]="cssVar(e.role)">
              <line class="ef-litwire" [attr.x1]="e.x1" [attr.y1]="e.y1" [attr.x2]="e.x2" [attr.y2]="e.y2" />
              <path class="ef-chevron c0" [attr.d]="CHEVRON" [attr.style]="e.path"></path>
              <path class="ef-chevron c1" [attr.d]="CHEVRON" [attr.style]="e.path"></path>
              <path class="ef-chevron c2" [attr.d]="CHEVRON" [attr.style]="e.path"></path>
              <path class="ef-arrow" [attr.d]="CHEVRON" [attr.style]="e.path"></path>
            </g>
          }
        }
      </svg>

      <!-- Nodes (HTML so the Bootstrap-Icon glyphs render natively) -->
      <div class="ef-node ef-node--inverter" [style.color]="cssVar(model().inverter)">
        <span class="ef-ring"><i class="bi bi-lightning-charge-fill"></i></span>
        <span class="ef-name">Inverter</span>
      </div>
      @for (n of cornerNodes(); track n.id) {
        <div class="ef-node" [class]="'ef-node--' + n.id" [style.color]="cssVar(n.role)">
          <span class="ef-ring"><i class="bi" [class]="n.icon"></i></span>
          <span class="ef-name">{{ n.name }}</span>
        </div>
      }
    </div>
  `,
  styles: [
    `
    .ef-widget {
      position: relative;
      width: 100%;
      max-width: 360px;
      aspect-ratio: 1;
      margin: 0 auto;
      container-type: inline-size;
    }
    .ef-svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }

    .ef-wire { stroke: var(--bs-border-color); stroke-width: 0.7; }

    .ef-edge { color: var(--bs-secondary); }
    /* The lit wire keeps the active edge's colour visible between chevrons. */
    .ef-litwire { stroke: currentColor; stroke-width: 1; opacity: 0.35; }
    .ef-chevron, .ef-arrow {
      fill: none;
      stroke: currentColor;
      stroke-width: 1.4;
      stroke-linecap: round;
      stroke-linejoin: round;
      offset-rotate: auto; /* align the chevron to its path's travel direction (offset-path set inline) */
    }
    /* Reduced-motion fallback: drop the travelling chevrons, keep one static arrowhead near the end. */
    .ef-arrow { display: none; offset-distance: 88%; }

    @media (prefers-reduced-motion: no-preference) {
      .ef-chevron { animation: ef-flow 1.8s linear infinite; }
      .ef-chevron.c1 { animation-delay: -1.2s; }
      .ef-chevron.c2 { animation-delay: -0.6s; }
    }
    @media (prefers-reduced-motion: reduce) {
      .ef-chevron { display: none; }
      .ef-arrow { display: inline; }
    }
    @keyframes ef-flow {
      0%   { offset-distance: 0%; opacity: 0; }
      15%  { opacity: 1; }
      85%  { opacity: 1; }
      100% { offset-distance: 100%; opacity: 0; }
    }

    .ef-node {
      position: absolute;
      transform: translate(-50%, -50%);
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 0.3rem;
    }
    .ef-node--inverter { left: 50%; top: 50%; }
    .ef-node--solar { left: 20%; top: 20%; }
    .ef-node--house { left: 80%; top: 20%; }
    .ef-node--battery { left: 20%; top: 80%; }
    .ef-node--grid { left: 80%; top: 80%; }

    .ef-ring {
      width: 22cqi;
      aspect-ratio: 1;
      border-radius: 50%;
      border: 0.18rem solid currentColor;
      display: flex;
      align-items: center;
      justify-content: center;
      background: var(--bs-body-bg);
      box-shadow: 0 0 0 0.18rem var(--bs-body-bg); /* mask the wires behind the ring */
    }
    .ef-node--inverter .ef-ring { width: 26cqi; }
    .ef-ring i { font-size: 9cqi; line-height: 1; color: currentColor; }
    .ef-name { font-size: 0.72rem; color: var(--bs-secondary-color); }
    `,
  ],
})
export class EnergyFlow {
  /** Normalized metric snapshot (canonical keys, §4). Null until the first reading arrives. */
  readonly metrics = input<Record<string, MetricValue> | null>(null);
  /** Whether the inverter is online / connected (drives the centre ring + suppresses all flow). */
  readonly inverterOnline = input<boolean>(true);

  /** Chevron pointing +x, centred on the origin; rotated per edge to the flow direction. */
  readonly CHEVRON = 'M -1.7 -1.9 L 1.4 0 L -1.7 1.9';

  readonly model = computed(() => computeEnergyFlow(this.metrics(), this.inverterOnline()));
  readonly edges = computed<RenderEdge[]>(() => this.model().edges.map(renderEdge));

  readonly cornerNodes = computed(() => {
    const m = this.model();
    const role: Record<EdgeId, FlowRole> = { solar: m.solar, house: m.house, battery: m.battery, grid: m.grid };
    return (Object.keys(CORNERS) as EdgeId[]).map((id) => ({ id, role: role[id], icon: CORNERS[id].icon, name: CORNERS[id].name }));
  });

  cssVar(role: FlowRole): string {
    return `var(--bs-${role})`;
  }

  ariaLabel(): string {
    const active = this.model().edges.filter((e) => e.active).length;
    return this.inverterOnline()
      ? `Energy flow — ${active} active flow(s)`
      : 'Energy flow — inverter offline';
  }
}
