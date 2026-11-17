import { HttpClient } from '@angular/common/http';
import { inject, Service } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { API_BASE_URL } from './api.config';

export interface Certificate {
  id: string;
  eventId: string;
  title: string;
  category: string;
  role: string;
  available: boolean;
}

@Service()
export class CertificateService {
  private readonly http = inject(HttpClient);
  private readonly api = inject(API_BASE_URL);

  list() {
    return firstValueFrom(
      this.http.get<Certificate[]>(`${this.api}/me/certificates`, { withCredentials: true }),
    );
  }

  download(id: string) {
    return `${this.api}/me/certificates/${encodeURIComponent(id)}`;
  }
}
