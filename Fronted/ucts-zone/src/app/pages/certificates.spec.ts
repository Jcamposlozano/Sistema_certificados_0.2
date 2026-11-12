import { TestBed } from '@angular/core/testing';
import { Certificates } from './certificates';
import { CertificateService } from '../core/certificate.service';

describe('Certificate access', () => {
  beforeEach(() => TestBed.configureTestingModule({ imports: [Certificates] }));

  it('rejects invalid emails before opening the OTP step', () => {
    const page = TestBed.createComponent(Certificates).componentInstance;
    page.emailForm.controls.email.setValue('invalid');
    page.requestCode();
    expect(page.step()).toBe('email');
    expect(TestBed.inject(CertificateService).email()).toBe('');
  });

  it('requires a valid demo code and clears access on logout', async () => {
    const fixture = TestBed.createComponent(Certificates);
    const page = fixture.componentInstance;
    page.emailForm.controls.email.setValue('participant@example.com');
    page.requestCode();
    expect(page.step()).toBe('otp');
    page.otpForm.controls.code.setValue('999999');
    page.verify();
    expect(page.service.authenticated()).toBe(false);
    expect(page.error()).toContain('no es correcto');
    page.otpForm.controls.code.setValue('123456');
    page.verify();
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelectorAll('.event-card')).toHaveLength(4);
    expect(element.querySelector<HTMLButtonElement>('.event-card:last-child button')?.disabled).toBe(true);
    page.category.set('Taller');
    await fixture.whenStable();
    expect(element.querySelectorAll('.event-card')).toHaveLength(1);
    page.logout();
    expect(page.service.authenticated()).toBe(false);
    expect(page.service.email()).toBe('');
    expect(page.step()).toBe('email');
  });
});
