import { TestBed } from '@angular/core/testing';
import { provideCharts, withDefaultRegisterables } from 'ng2-charts';

import { TimeSeriesChart } from './time-series-chart';
import { HistoryPoint } from '../core/models';

describe('TimeSeriesChart', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TimeSeriesChart],
      providers: [provideCharts(withDefaultRegisterables())],
    }).compileComponents();
  });

  it('renders with sample points without error', () => {
    const fixture = TestBed.createComponent(TimeSeriesChart);
    const pts: HistoryPoint[] = [
      { ts: 1_700_000_000, value: 100 },
      { ts: 1_700_003_600, value: 200 },
    ];
    fixture.componentRef.setInput('points', pts);
    fixture.componentRef.setInput('label', 'PV power');
    fixture.componentRef.setInput('unit', 'W');
    fixture.detectChanges();

    const data = fixture.componentInstance.data();
    expect(data.labels?.length).toBe(2);
    expect(data.datasets[0].data).toEqual([100, 200]);
    expect(fixture.nativeElement.querySelector('canvas')).toBeTruthy();
  });

  it('uses last and scale for counter metrics', () => {
    const fixture = TestBed.createComponent(TimeSeriesChart);
    fixture.componentRef.setInput('points', [{ ts: 1, value: 0, last: 2000 }] as HistoryPoint[]);
    fixture.componentRef.setInput('label', 'Today PV');
    fixture.componentRef.setInput('useLast', true);
    fixture.componentRef.setInput('scale', 1000);
    fixture.detectChanges();
    expect(fixture.componentInstance.data().datasets[0].data).toEqual([2]);
  });

  it('adds a second dataset on a right-hand axis when overlayPoints are given', () => {
    const fixture = TestBed.createComponent(TimeSeriesChart);
    fixture.componentRef.setInput('points', [
      { ts: 1, value: 4200 },
      { ts: 2, value: 3800 },
    ] as HistoryPoint[]);
    fixture.componentRef.setInput('label', 'Expected PV');
    fixture.componentRef.setInput('overlayPoints', [
      { ts: 1, value: 20 },
      { ts: 2, value: 45 },
    ] as HistoryPoint[]);
    fixture.componentRef.setInput('overlayUnit', '%');
    fixture.componentRef.setInput('overlayMin', 0);
    fixture.componentRef.setInput('overlayMax', 100);
    fixture.detectChanges();

    const data = fixture.componentInstance.data();
    expect(data.datasets.length).toBe(2);
    expect((data.datasets[0] as { yAxisID?: string }).yAxisID).toBe('y');
    expect((data.datasets[1] as { yAxisID?: string }).yAxisID).toBe('y1');
    expect(data.datasets[1].data).toEqual([20, 45]);

    const scales = fixture.componentInstance.options()?.scales as Record<string, any>;
    expect(scales['y1'].position).toBe('right');
    expect(scales['y1'].min).toBe(0);
    expect(scales['y1'].max).toBe(100);
    expect(scales['y1'].grid.drawOnChartArea).toBe(false);
  });

  it('applies fixed/suggested bounds to the primary Y axis', () => {
    const fixture = TestBed.createComponent(TimeSeriesChart);
    fixture.componentRef.setInput('points', [{ ts: 1, value: 50 }] as HistoryPoint[]);
    fixture.componentRef.setInput('label', 'Projected SoC');
    fixture.componentRef.setInput('yMin', 0);
    fixture.componentRef.setInput('yMax', 100);
    fixture.componentRef.setInput('ySuggestedMax', 6500);
    fixture.detectChanges();
    const y = (fixture.componentInstance.options()?.scales as Record<string, any>)['y'];
    expect(y.min).toBe(0);
    expect(y.max).toBe(100);
    expect(y.suggestedMax).toBe(6500);
  });

  it('renders a single dataset and no y1 axis without an overlay', () => {
    const fixture = TestBed.createComponent(TimeSeriesChart);
    fixture.componentRef.setInput('points', [{ ts: 1, value: 100 }] as HistoryPoint[]);
    fixture.componentRef.setInput('label', 'PV power');
    fixture.detectChanges();
    expect(fixture.componentInstance.data().datasets.length).toBe(1);
    const scales = fixture.componentInstance.options()?.scales as Record<string, any>;
    expect(scales['y1']).toBeUndefined();
  });
});
