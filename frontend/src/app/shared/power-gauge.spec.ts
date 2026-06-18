import { TestBed } from '@angular/core/testing';

import { PowerGauge } from './power-gauge';

describe('PowerGauge', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [PowerGauge] }).compileComponents();
  });

  function mount(inputs: Record<string, unknown>) {
    const fixture = TestBed.createComponent(PowerGauge);
    for (const [k, v] of Object.entries(inputs)) fixture.componentRef.setInput(k, v);
    fixture.detectChanges();
    return fixture;
  }

  it('shows the real value + unit — no kW conversion or rounding', () => {
    expect(mount({ value: 441 }).componentInstance.valueText()).toBe('441 W');
    expect(mount({ value: 6543.2 }).componentInstance.valueText()).toBe('6543.2 W'); // not "6.5 kW"
    expect(mount({ value: 0 }).componentInstance.valueText()).toBe('0 W');
  });

  it('keeps non-watt units as-is', () => {
    expect(mount({ value: 52.3, unit: 'V' }).componentInstance.valueText()).toBe('52.3 V');
  });

  it('fills the ring as value/max and caps at 100%', () => {
    expect(mount({ value: 4000, max: 8000 }).componentInstance.fraction()).toBe(0.5);
    expect(mount({ value: 9000, max: 8000 }).componentInstance.fraction()).toBe(1); // capped
    expect(mount({ value: -3000, max: 6000 }).componentInstance.fraction()).toBe(0.5); // magnitude
  });

  it('renders the label and optional sublabel', () => {
    const el = mount({ value: 2000, label: 'Grid', sublabel: 'exporting' }).nativeElement as HTMLElement;
    expect(el.textContent).toContain('Grid');
    expect(el.textContent).toContain('exporting');
    expect(el.querySelector('svg')).toBeTruthy();
  });
});
