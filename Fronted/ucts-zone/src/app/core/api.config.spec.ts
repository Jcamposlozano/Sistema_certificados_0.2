import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../environments/environment';
import { environment as production } from '../../environments/environment.production';
import { API_BASE_URL } from './api.config';
import { AuthService } from './auth.service';
import { CertificateService } from './certificate.service';

describe('API URLs and session credentials', () => {
  for (const base of [environment.apiBaseUrl, production.apiBaseUrl]) {
    describe(base, () => {
      beforeEach(() =>
        TestBed.configureTestingModule({
          providers: [
            provideHttpClient(),
            provideHttpClientTesting(),
            { provide: API_BASE_URL, useValue: base },
          ],
        }),
      );
      afterEach(() => TestBed.inject(HttpTestingController).verify());

      it('preserves OTP, profile, logout and certificate routes with credentials', async () => {
        const auth = TestBed.inject(AuthService);
        const certificates = TestBed.inject(CertificateService);
        const http = TestBed.inject(HttpTestingController);
        const calls = [
          {
            promise: auth.requestCode('test@example.org'),
            method: 'POST',
            path: '/auth/otp/request',
          },
          {
            promise: auth.verifyCode('challenge', '123456'),
            method: 'POST',
            path: '/auth/otp/verify',
          },
          { promise: auth.profile(), method: 'GET', path: '/me' },
          { promise: auth.logout(), method: 'POST', path: '/auth/logout' },
          { promise: certificates.list(), method: 'GET', path: '/me/certificates' },
        ];
        for (const call of calls) {
          const request = http.expectOne(base + call.path);
          expect(request.request.method).toBe(call.method);
          expect(request.request.withCredentials).toBe(true);
          expect(request.request.url).not.toContain('/api/api/');
          request.flush(call.method === 'GET' ? [] : {});
          await call.promise;
        }
        expect(certificates.download('id/with space')).toBe(
          base + '/me/certificates/id%2Fwith%20space',
        );
      });
    });
  }

  it('uses the production API subdomain and one API prefix', () => {
    expect(production.apiBaseUrl).toBe('https://api.uctszone.net/api');
    expect(environment.apiBaseUrl).toBe('/api');
  });
});
