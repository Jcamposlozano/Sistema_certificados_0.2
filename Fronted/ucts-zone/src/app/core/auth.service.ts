import { HttpClient } from '@angular/common/http';
import { inject, Service } from '@angular/core';
import { firstValueFrom } from 'rxjs';

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

  requestCode(email: string) {
    return firstValueFrom(this.http.post<OtpChallenge>('/api/auth/otp/request', { email }));
  }

  verifyCode(challengeId: string, code: string) {
    return firstValueFrom(this.http.post<void>('/api/auth/otp/verify', { challengeId, code }));
  }

  profile() {
    return firstValueFrom(this.http.get<Profile>('/api/me'));
  }

  logout() {
    return firstValueFrom(this.http.post<void>('/api/auth/logout', {}));
  }
}
