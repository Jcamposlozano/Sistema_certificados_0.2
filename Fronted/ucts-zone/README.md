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
de desarrollo. En producción, el environment dirige las solicitudes al subdominio HTTPS
`api.uctszone.net`.

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

## API de producción

La URL se centraliza en `API_BASE_URL`, que lee el environment seleccionado al
compilar. Desarrollo usa `/api` y el proxy local. Producción usa
`https://api.uctszone.net/api`. Los servicios agregan rutas como `/me` o
`/auth/otp/request`. El prefijo `/api` forma parte únicamente de la base.

Todas las llamadas HTTP de autenticación y consulta usan `withCredentials`.
La descarga navega a la URL absoluta del certificado en el mismo subdominio
de la API. La cookie del backend es HttpOnly, Secure en producción, host-only
y con `Path=/api`. Ambos dominios HTTPS son del mismo sitio, así que
`SameSite=Lax` permite el uso de la sesión entre el portal y la API.
El backend debe permitir exactamente `https://uctszone.net` en CORS y aceptar
credenciales. `compose.ec2.yaml` ya proporciona esa configuración por defecto.
Conserva `UCTS_PUBLIC_HOSTNAME=uctszone.net` para el portal, aunque FastAPI
reciba `Host: api.uctszone.net`.

### Compilación y entrega tras aprobar el PR

```bash
npm ci
npm test -- --watch=false
npm run build -- --configuration production
```

Publica el contenido de `dist/ucts-zone/browser/` usando el procedimiento
habitual de entrega del frontend. La URL de producción queda incorporada en
los archivos compilados. Si sirves Angular desde Docker, desde la raíz del
proyecto construye y vuelve a crear el frontend:

```bash
docker compose -f compose.beta.yaml -f compose.ec2.yaml build frontend
docker compose -f compose.beta.yaml -f compose.ec2.yaml up -d --no-deps frontend
```

Después de publicar, verifica en la pestaña Network del navegador que solicitar
y verificar OTP, consultar `/api/me` y cerrar sesión se dirigen a
`https://api.uctszone.net/api/...`. Comprueba `Set-Cookie` en la verificación,
el envío de la cookie al consultar el perfil y el cierre de sesión. La API
debe responder al preflight desde `https://uctszone.net` con ese origen exacto
y `Access-Control-Allow-Credentials: true`.

Para rollback, vuelve a publicar el artefacto anterior o reconstruye y
recrea el frontend desde la revisión previamente desplegada. Esta entrega
requiere que DNS, TLS y la ruta pública del subdominio de API estén disponibles.
