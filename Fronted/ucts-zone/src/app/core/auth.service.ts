import { HttpClient } from '@angular/common/http';
import { inject, Service } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { API_BASE_URL } from './api.config';

export interface Profile {
  id: string;
  name: string;
  email: string;
}

export interface OtpChallenge {
  challengeId: string;
  expiresIn: number;
  resendAfter: number;
  message: string;
}

@Service()
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly api = inject(API_BASE_URL);

  requestCode(email: string) {
    return firstValueFrom(
      this.http.post<OtpChallenge>(
        `${this.api}/auth/otp/request`,
        { email },
        { withCredentials: true },
      ),
    );
  }

  verifyCode(challengeId: string, code: string) {
    return firstValueFrom(
      this.http.post<void>(
        `${this.api}/auth/otp/verify`,
        { challengeId, code },
        { withCredentials: true },
      ),
    );
  }

  profile() {
    return firstValueFrom(this.http.get<Profile>(`${this.api}/me`, { withCredentials: true }));
  }

  logout() {
    return firstValueFrom(
      this.http.post<void>(`${this.api}/auth/logout`, {}, { withCredentials: true }),
    );
  }
}
