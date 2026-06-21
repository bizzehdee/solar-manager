import { TestBed } from '@angular/core/testing';

import { MetricCard } from './metric-card';

describe('MetricCard', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [MetricCard] }).compileComponents();
  });

  function create(value: unknown, label = 'X') {
    const fixture = TestBed.createComponent(MetricCard);
    fixture.componentRef.setInput('label', label);
    if (value !== undefined) fixture.componentRef.setInput('value', value);
    fixture.detectChanges();
    return fixture;
  }

  it('decimal-formats a numeric value with unit and label', () => {
    const fixture = create(3200.1234, 'Solar');
    fixture.componentRef.setInput('unit', 'W');
    fixture.detectChanges();
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('3,200.123'); // 1.0-3 → max 3 dp, grouped
    expect(text).toContain('W');
    expect(text).toContain('Solar');
  });

  it('renders a preformatted string value as-is (text metric)', () => {
    const text = (create('GBP 1.23', 'Savings').nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('GBP 1.23');
    expect(text).toContain('Savings');
  });

  it('renders a string-array value comma-joined', () => {
    const text = (create(['eco', 'boost']).nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('eco, boost');
  });

  it('renders an em-dash when the value is undefined (missing ≠ zero)', () => {
    const fixture = create(undefined, 'Peak PV');
    expect(fixture.componentInstance.isMissing()).toBe(true);
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('—');
  });

  it('renders an em-dash when the value is null', () => {
    expect((create(null).nativeElement as HTMLElement).textContent).toContain('—');
  });

  it('renders an optional hint line', () => {
    const fixture = create(42);
    fixture.componentRef.setInput('hint', 'updated just now');
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('updated just now');
  });
});
