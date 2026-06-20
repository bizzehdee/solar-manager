import { TestBed } from '@angular/core/testing';

import { DialogHost } from './dialog';
import { DialogService } from '../core/dialog.service';

describe('DialogHost + DialogService', () => {
  let svc: DialogService;

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [DialogHost] }).compileComponents();
    svc = TestBed.inject(DialogService);
  });

  it('renders nothing until a dialog is requested', () => {
    const fixture = TestBed.createComponent(DialogHost);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.modal')).toBeNull();
  });

  it('prompt resolves with the trimmed input value on OK', async () => {
    const fixture = TestBed.createComponent(DialogHost);
    fixture.detectChanges();
    const result = svc.prompt({ title: 'New dashboard', label: 'Name' });
    fixture.detectChanges();

    expect((fixture.nativeElement as HTMLElement).textContent).toContain('New dashboard');
    fixture.componentInstance.value = '  Garage  ';
    fixture.componentInstance.ok();
    expect(await result).toBe('Garage');
    // Modal closed afterwards.
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.modal')).toBeNull();
  });

  it('prompt resolves null when blank or cancelled', async () => {
    const fixture = TestBed.createComponent(DialogHost);
    const blank = svc.prompt({ title: 'X' });
    fixture.detectChanges();
    fixture.componentInstance.value = '   ';
    fixture.componentInstance.ok();
    expect(await blank).toBeNull();

    const cancelled = svc.prompt({ title: 'X' });
    fixture.detectChanges();
    fixture.componentInstance.cancel();
    expect(await cancelled).toBeNull();
  });

  it('confirm resolves true on OK and false on cancel', async () => {
    const fixture = TestBed.createComponent(DialogHost);
    const yes = svc.confirm({ title: 'Delete', message: 'Sure?', danger: true });
    fixture.detectChanges();
    fixture.componentInstance.ok();
    expect(await yes).toBe(true);

    const no = svc.confirm({ title: 'Delete', message: 'Sure?' });
    fixture.detectChanges();
    fixture.componentInstance.cancel();
    expect(await no).toBe(false);
  });
});
