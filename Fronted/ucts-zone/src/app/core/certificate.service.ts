import { HttpClient } from '@angular/common/http';
import { inject, Service } from '@angular/core';
import { firstValueFrom } from 'rxjs';

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

  list() {
    return firstValueFrom(this.http.get<Certificate[]>('/api/me/certificates'));
  }

  download(id: string) {
    return `/api/me/certificates/${encodeURIComponent(id)}`;
  }
}
