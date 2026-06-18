import { TestBed } from '@angular/core/testing';

import { SettingValue } from './setting-value';
import { SettingsField } from '../core/models';

function render(field: SettingsField, value: unknown): string {
  const fixture = TestBed.createComponent(SettingValue);
  fixture.componentRef.setInput('field', field);
  fixture.componentRef.setInput('value', value);
  fixture.detectChanges();
  return (fixture.nativeElement as HTMLElement).textContent?.trim() ?? '';
}

describe('SettingValue', () => {
  beforeEach(() => TestBed.configureTestingModule({ imports: [SettingValue] }));

  it('renders a bool as Yes/No', () => {
    expect(render({ key: 'b', label: 'B', type: 'bool' }, true)).toBe('Yes');
    expect(render({ key: 'b', label: 'B', type: 'bool' }, false)).toBe('No');
  });

  it('renders an enum as its option label, falling back to the raw value', () => {
    const f: SettingsField = {
      key: 'm', label: 'Mode', type: 'enum',
      options: [{ value: 2, label: 'Zero export to CT' }],
    };
    expect(render(f, 2)).toBe('Zero export to CT');
    expect(render(f, 9)).toBe('9'); // unknown value
  });

  it('appends the unit to numbers and shows time as-is', () => {
    expect(render({ key: 'v', label: 'V', type: 'number', unit: 'V' }, 53.6)).toBe('53.6 V');
    expect(render({ key: 't', label: 'T', type: 'time' }, '00:05')).toBe('00:05');
  });

  it('renders an em-dash for null/undefined', () => {
    expect(render({ key: 'x', label: 'X', type: 'number', unit: 'W' }, null)).toBe('—');
    expect(render({ key: 'x', label: 'X', type: 'bool' }, undefined)).toBe('—');
  });
});
