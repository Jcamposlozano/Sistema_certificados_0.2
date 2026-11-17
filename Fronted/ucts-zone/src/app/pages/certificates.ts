import { HttpErrorResponse } from '@angular/common/http';
import { afterNextRender, Component, DestroyRef, DOCUMENT, inject, signal } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { AuthService, Profile } from '../core/auth.service';
import { Certificate, CertificateService } from '../core/certificate.service';

@Component({
  selector: 'app-certificates',
  imports: [ReactiveFormsModule],
  styleUrl: './certificates.scss',
  templateUrl: './certificates.html',
})
export class Certificates {
  private readonly auth = inject(AuthService);
  private readonly certificates = inject(CertificateService);
  private readonly document = inject(DOCUMENT);
  private readonly destroy = inject(DestroyRef);
  private challengeId = '';
  private email = '';
  private timer?: ReturnType<typeof setTimeout>;

  readonly profile = signal<Profile | null>(null);
  readonly items = signal<Certificate[] | null>(null);
  readonly step = signal<'email' | 'otp'>('email');
  readonly busy = signal(true);
  readonly resendBlocked = signal(false);
  readonly error = signal('');
  readonly message = signal('');
  readonly emailForm = new FormGroup({
    email: new FormControl('', {
      nonNullable: true,
      validators: [Validators.required, Validators.email, Validators.maxLength(254)],
    }),
  });
  readonly otpForm = new FormGroup({
    code: new FormControl('', {
      nonNullable: true,
      validators: [Validators.required, Validators.pattern(/^[0-9]{6,8}$/)],
    }),
  });

  constructor() {
    afterNextRender(() => void this.restoreSession());
    this.destroy.onDestroy(() => clearTimeout(this.timer));
  }

  async restoreSession() {
    try {
      const profile = await this.auth.profile();
      this.profile.set(profile);
      await this.loadCertificates();
    } catch (error) {
      if (!(error instanceof HttpErrorResponse && error.status === 401)) {
        this.error.set('No fue posible consultar la sesión. Intenta nuevamente.');
      }
    } finally {
      this.busy.set(false);
    }
  }

  async requestCode() {
    this.emailForm.markAllAsTouched();
    if (this.emailForm.invalid || this.busy()) return;
    await this.sendCode(this.emailForm.controls.email.value.trim());
  }

  async resend() {
    if (this.busy() || this.resendBlocked()) return;
    await this.sendCode(this.email);
  }

  private async sendCode(email: string) {
    this.busy.set(true);
    this.error.set('');
    this.message.set('');
    try {
      const challenge = await this.auth.requestCode(email);
      this.email = email;
      this.challengeId = challenge.challengeId;
      this.otpForm.reset();
      this.step.set('otp');
      this.message.set(challenge.message);
      this.delayResend(challenge.resendAfter);
      this.focus('otp');
    } catch (error) {
      if (error instanceof HttpErrorResponse && error.status === 429) {
        const wait = Number(error.headers.get('Retry-After'));
        this.delayResend(wait > 0 ? wait : 60);
        this.error.set('Demasiados intentos. Espera antes de solicitar otro código.');
      } else {
        this.error.set('No fue posible solicitar el código. Intenta nuevamente.');
      }
    } finally {
      this.busy.set(false);
    }
  }

  private delayResend(seconds: number) {
    clearTimeout(this.timer);
    this.resendBlocked.set(true);
    this.timer = setTimeout(() => this.resendBlocked.set(false), seconds * 1000);
  }

  async verify() {
    this.otpForm.markAllAsTouched();
    if (this.otpForm.invalid || this.busy() || !this.challengeId) return;
    this.busy.set(true);
    this.error.set('');
    try {
      await this.auth.verifyCode(this.challengeId, this.otpForm.controls.code.value);
      this.resetChallenge();
      await this.restoreSession();
      this.focus(this.profile() ? 'certificates-heading' : 'email');
    } catch (error) {
      this.error.set(
        error instanceof HttpErrorResponse && error.status === 401
          ? 'Código inválido o vencido. Revisa el código o solicita uno nuevo.'
          : 'No fue posible verificar el código. Intenta nuevamente.',
      );
    } finally {
      this.busy.set(false);
    }
  }

  changeEmail() {
    this.resetChallenge();
    this.error.set('');
    this.focus('email');
  }

  async logout() {
    if (this.busy()) return;
    this.busy.set(true);
    this.error.set('');
    try {
      await this.auth.logout();
      this.profile.set(null);
      this.items.set(null);
      this.emailForm.reset();
      this.changeEmail();
    } catch {
      this.error.set('No fue posible cerrar la sesión. Intenta nuevamente.');
    } finally {
      this.busy.set(false);
    }
  }

  async loadCertificates() {
    this.error.set('');
    try {
      this.items.set(await this.certificates.list());
    } catch (error) {
      if (error instanceof HttpErrorResponse && error.status === 401) {
        this.profile.set(null);
        this.items.set(null);
        this.error.set('Tu sesión venció. Ingresa nuevamente.');
      } else {
        this.error.set('No fue posible consultar tus certificados.');
      }
    }
  }

  download(id: string) {
    return this.certificates.download(id);
  }

  private resetChallenge() {
    clearTimeout(this.timer);
    this.resendBlocked.set(false);
    this.step.set('email');
    this.challengeId = '';
    this.email = '';
    this.otpForm.reset();
    this.message.set('');
  }

  private focus(id: string) {
    setTimeout(() => this.document.getElementById(id)?.focus());
  }
}
