import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Certificates } from './certificates';

describe('Acceso al portal de certificados', () => {
  beforeEach(() =>
    TestBed.configureTestingModule({
      imports: [Certificates],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }),
  );

  afterEach(() => TestBed.inject(HttpTestingController).verify());

  function open() {
    const fixture = TestBed.createComponent(Certificates);
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    return { fixture, page: fixture.componentInstance, http };
  }

  it('valida el correo y solicita un desafío al backend', async () => {
    const { page, http } = open();
    http.expectOne('/api/me').flush({}, { status: 401, statusText: 'Unauthorized' });
    await Promise.resolve();

    page.emailForm.controls.email.setValue('incorrecto');
    await page.requestCode();
    http.expectNone('/api/auth/otp/request');

    page.emailForm.controls.email.setValue('participante@example.org');
    const request = page.requestCode();
    const otp = http.expectOne('/api/auth/otp/request');
    expect(otp.request.body).toEqual({ email: 'participante@example.org' });
    otp.flush({
      challengeId: 'desafio-de-prueba',
      resendAfter: 60,
      expiresIn: 180,
      message: 'Si tu cuenta permite el acceso, recibirás un código en tu correo.',
    });
    await request;
    expect(page.step()).toBe('otp');
    expect(page.resendBlocked()).toBe(true);

    page.otpForm.controls.code.setValue('111111');
    const invalid = page.verify();
    http.expectOne('/api/auth/otp/verify').flush({}, { status: 401, statusText: 'Unauthorized' });
    await invalid;
    expect(page.profile()).toBeNull();
    expect(page.error()).toContain('Código inválido o vencido');

    page.otpForm.controls.code.setValue('111222');
    const valid = page.verify();
    const verification = http.expectOne('/api/auth/otp/verify');
    expect(verification.request.body).toEqual({
      challengeId: 'desafio-de-prueba',
      code: '111222',
    });
    verification.flush(null, { status: 204, statusText: 'No Content' });
    await Promise.resolve();
    http.expectOne('/api/me').flush({
      id: 'persona',
      name: 'Participante de prueba',
      email: 'participante@example.org',
    });
    await Promise.resolve();
    http.expectOne('/api/me/certificates').flush([
      {
        id: 'certificado',
        title: 'Taller de prueba',
        role: 'Asistente',
        available: false,
      },
    ]);
    await valid;
    expect(page.items()?.length).toBe(1);

    const logout = page.logout();
    http.expectOne('/api/auth/logout').flush(null, { status: 204, statusText: 'No Content' });
    await logout;
    expect(page.profile()).toBeNull();
    expect(page.items()).toBeNull();
  });
});
