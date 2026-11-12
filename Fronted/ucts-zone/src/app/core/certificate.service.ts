import { Injectable, signal } from '@angular/core';
export interface UctsEvent { id: string; title: string; category: string; date: string; hours: number; available: boolean; }
/** Demo adapter. Replace its methods with the REST endpoints documented in README.md. */
@Injectable({ providedIn: 'root' })
export class CertificateService {
  readonly email = signal('');
  readonly authenticated = signal(false);
  readonly events: readonly UctsEvent[] = [
    { id:'innovation', title:'Encuentro de innovación y tecnología', category:'Encuentro', date:'18 de octubre de 2026', hours:8, available:true },
    { id:'leadership', title:'Liderazgo que transforma', category:'Taller', date:'24 de septiembre de 2026', hours:4, available:true },
    { id:'community', title:'Conectando conocimiento, creando comunidad', category:'Conferencia', date:'12 de agosto de 2026', hours:2, available:true },
    { id:'research', title:'Jornada de investigación UCTS', category:'Jornada', date:'5 de noviembre de 2026', hours:6, available:false }
  ];
  requestCode(email: string) { this.email.set(email); }
  verifyCode(code: string): boolean { const valid = code === '123456'; this.authenticated.set(valid); return valid; }
  signOut() { this.authenticated.set(false); this.email.set(''); }
  download(event: UctsEvent) {
    if (!this.authenticated() || !event.available) throw new Error('Certificado no disponible');
    const clean = (value: string) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^\x20-\x7E]/g, '').replace(/[()\\]/g, '');
    const lines = ['UCTS / ZONE', 'CERTIFICADO DE DEMOSTRACION', 'Documento de prueba sin validez oficial', clean(event.title), clean(this.email()), clean(event.date), `${event.hours} horas de participacion`];
    const stream = 'BT /F1 22 Tf 70 730 Td ' + lines.map((line, i) => `${i ? '0 -65 Td ' : ''}(${line}) Tj`).join('\n') + '\nET';
    const objects = ['<< /Type /Catalog /Pages 2 0 R >>','<< /Type /Pages /Kids [3 0 R] /Count 1 >>','<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>','<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`];
    let pdf = '%PDF-1.4\n'; const offsets = [0];
    objects.forEach((object, i) => { offsets.push(pdf.length); pdf += `${i+1} 0 obj\n${object}\nendobj\n`; });
    const start = pdf.length;
    pdf += `xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map(offset => `${String(offset).padStart(10,'0')} 00000 n \n`).join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${start}\n%%EOF`;
    const url = URL.createObjectURL(new Blob([pdf], {type:'application/pdf'}));
    const link = document.createElement('a'); link.href = url; link.download = `demo-ucts-${event.id}.pdf`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
