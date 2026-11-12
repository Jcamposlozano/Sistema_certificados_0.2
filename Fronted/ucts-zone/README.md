# UCTS Zone · Frontend

Angular 22, componentes independientes, rutas con carga diferida y estado con signals.

## Ejecutar

Usa Node 24.22.1 (o una versión compatible con Angular 22).

```sh
npm install
npm start
```

Abre http://localhost:4200. Home está en `/` y Certificados en `/certificados`.

## Probar la demo

1. Entra a Certificados e ingresa un correo válido.
2. Usa el OTP **123456**. Prueba otro código para ver el error.
3. Filtra eventos y descarga un PDF de demostración. Los pendientes no permiten descarga.
4. Cierra sesión para volver al acceso.

No hay envío de correo ni autenticación real. Los datos son ficticios y la sesión vive únicamente en memoria; recargar la página cierra el acceso. Los PDF indican que no tienen validez oficial.

## Organización

- `src/app/pages/home.*`: presentación de la plataforma.
- `src/app/pages/certificates.*`: acceso y consulta de eventos.
- `src/app/core/certificate.service.ts`: adaptador de demostración y modelo de evento.
- `src/app/app.*`: navegación y estructura compartida.

## Contrato REST propuesto (pendiente de implementar)

| Método | Ruta | Respuesta |
| --- | --- | --- |
| POST | `/api/auth/otp/request` | Recibe `{ email }`; devuelve `{ challengeId, expiresIn, resendAfter }`. |
| POST | `/api/auth/otp/verify` | Recibe `{ challengeId, code }`; establece una sesión autenticada. |
| POST | `/api/auth/logout` | Invalida la sesión. |
| GET | `/api/me/events` | Devuelve eventos del usuario con `id`, `title`, `category`, `date`, `hours`, `available`. |
| GET | `/api/me/events/:id/certificate` | Devuelve bytes PDF, `Content-Type: application/pdf`, `Content-Disposition: attachment; filename="certificado.pdf"`. |

El frontend reemplazará el adaptador demo con HttpClient y descargará el PDF como Blob. Alternativamente el endpoint puede devolver `{ downloadUrl, expiresAt }` con una URL firmada temporal de S3; elegir un contrato antes de integrar.

La API debe identificar al usuario desde la sesión verificada, comprobar su participación y habilitación en cada descarga y nunca confiar en el correo, ID o estado `available` enviado por el navegador. Usar errores 401 (sesión), 403 (no habilitado), 404 (no encontrado) y 429 (límite de OTP), y devolver mensajes seguros. Para sesiones con cookies: HttpOnly, Secure, SameSite y protección CSRF apropiada; preferir API bajo el mismo origen.

### Cognito

Cognito tiene autenticación nativa con EMAIL_OTP mediante USER_AUTH. Requiere configurar el user pool, app client, usuarios y entrega de correo con SES; OTP por email requiere plan Essentials o superior. El backend administra el desafío y verifica la respuesta. Nunca colocar secretos AWS ni secretos del app client en Angular. El código de demostración y la validación local se eliminan al conectar el servicio real; la longitud del código se ajusta al desafío real.

Referencias: https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-authentication-flow-methods.html y https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-email.html

## Validación

```sh
npm run build
npm test -- --watch=false
```
