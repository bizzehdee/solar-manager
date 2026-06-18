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
});
