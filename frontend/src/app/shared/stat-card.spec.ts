import { TestBed } from '@angular/core/testing';

import { StatCard } from './stat-card';

describe('StatCard', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [StatCard] }).compileComponents();
  });

  it('renders a preformatted string value with unit and label', () => {
    const fixture = TestBed.createComponent(StatCard);
    fixture.componentRef.setInput('label', 'Savings');
    fixture.componentRef.setInput('value', 'GBP 1.23');
    fixture.detectChanges();
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('GBP 1.23');
    expect(text).toContain('Savings');
  });

  it('renders a numeric value', () => {
    const fixture = TestBed.createComponent(StatCard);
    fixture.componentRef.setInput('label', 'Cycles');
    fixture.componentRef.setInput('value', 42);
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('42');
  });

  it('renders — when value is undefined', () => {
    const fixture = TestBed.createComponent(StatCard);
    fixture.componentRef.setInput('label', 'Peak PV');
    fixture.detectChanges();
    expect(fixture.componentInstance.isMissing()).toBe(true);
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('—');
  });

  it('renders — when value is null', () => {
    const fixture = TestBed.createComponent(StatCard);
    fixture.componentRef.setInput('label', 'Peak PV');
    fixture.componentRef.setInput('value', null);
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('—');
  });
});
