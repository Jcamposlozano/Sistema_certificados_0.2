import { Routes } from '@angular/router';
export const routes: Routes = [
  { path: '', title: 'Home · UCTS Zone', loadComponent: () => import('./pages/home').then(m => m.Home) },
  { path: 'certificados', title: 'Certificados · UCTS Zone', loadComponent: () => import('./pages/certificates').then(m => m.Certificates) },
  { path: '**', redirectTo: '' }
];
