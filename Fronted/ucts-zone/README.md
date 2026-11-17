# UCTS Zone · Frontend

Angular 22 con componentes independientes y rutas con carga diferida. Home está
en `/` y el portal de certificados en `/certificados`.

## Ejecutar

Primero prepara FastAPI y el app client siguiendo la
[guía del backend para Cognito](../../Backend/docs/cognito.md). Con una versión de
Node compatible con Angular 22, ejecuta:

```sh
npm ci
npm start
```

Abre `http://localhost:4200/certificados` e ingresa con el correo principal
registrado en UCTS. Angular envía las solicitudes `/api/*` a FastAPI por el proxy
de desarrollo. En un despliegue, dirige esas mismas rutas al backend bajo el
origen HTTPS del frontend.

## Organización

- `src/app/pages/certificates.*` contiene el formulario de acceso y la lista de certificados.
- `src/app/core/auth.service.ts` solicita y verifica el código, consulta la sesión y la cierra.
- `src/app/core/certificate.service.ts` consulta los certificados de la sesión y ofrece la descarga cuando la API la habilita.

| Método | Ruta | Uso |
| --- | --- | --- |
| POST | `/api/auth/otp/request` | Iniciar el desafío con un correo |
| POST | `/api/auth/otp/verify` | Verificar el código y establecer una cookie de sesión |
| POST | `/api/auth/logout` | Cerrar la sesión |
| GET | `/api/me` | Consultar el perfil de la sesión |
| GET | `/api/me/certificates` | Listar certificados de la sesión |
| GET | `/api/me/certificates/:id` | Descargar un certificado habilitado |

## Validar

```sh
npm run build
npm test -- --watch=false
```
