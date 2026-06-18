import { TestBed } from '@angular/core/testing';

import { SettingInput } from './setting-input';
import { SettingsField } from '../core/models';

describe('SettingInput', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [SettingInput] }).compileComponents();
  });

  function mount(field: SettingsField, value: unknown) {
    const fixture = TestBed.createComponent(SettingInput);
    fixture.componentRef.setInput('field', field);
    fixture.componentRef.setInput('value', value);
    const emitted: unknown[] = [];
    fixture.componentInstance.valueChange.subscribe((v) => emitted.push(v));
    fixture.detectChanges();
    return { fixture, emitted, el: fixture.nativeElement as HTMLElement };
  }

  it('renders a checkbox for bool and emits a boolean', () => {
    const { el, emitted } = mount({ key: 'g', label: 'Grid charge', type: 'bool' }, false);
    const cb = el.querySelector('input[type=checkbox]') as HTMLInputElement;
    expect(cb).toBeTruthy();
    cb.checked = true;
    cb.dispatchEvent(new Event('change'));
    expect(emitted).toEqual([true]);
  });

  it('renders a select for enum and emits the numeric machine value', () => {
    const { el, emitted } = mount(
      {
        key: 'work_mode',
        label: 'Work mode',
        type: 'enum',
        options: [
          { value: 0, label: 'Selling first' },
          { value: 2, label: 'Zero export to CT' },
        ],
      },
      0,
    );
    const sel = el.querySelector('select') as HTMLSelectElement;
    expect(sel.querySelectorAll('option').length).toBe(2);
    sel.value = '2';
    sel.dispatchEvent(new Event('change'));
    expect(emitted).toEqual([2]);
  });

  it('renders a number input with min/max and emits a number (or null when cleared)', () => {
    const { el, emitted } = mount(
      { key: 'soc', label: 'Target SoC', type: 'number', unit: '%', min: 0, max: 100 },
      65,
    );
    const input = el.querySelector('input[type=number]') as HTMLInputElement;
    expect(input.min).toBe('0');
    expect(input.max).toBe('100');
    input.value = '80';
    input.dispatchEvent(new Event('input'));
    input.value = '';
    input.dispatchEvent(new Event('input'));
    expect(emitted).toEqual([80, null]);
  });

  it('renders a time input and emits the HH:MM string', () => {
    const { el, emitted } = mount({ key: 'start_time', label: 'Start', type: 'time' }, '00:05');
    const input = el.querySelector('input[type=time]') as HTMLInputElement;
    expect(input.value).toBe('00:05');
    input.value = '06:30';
    input.dispatchEvent(new Event('change'));
    expect(emitted).toEqual(['06:30']);
  });
});
