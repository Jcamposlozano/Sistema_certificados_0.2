# Beta UCTS con Docker Compose y SQLite

La beta tiene dos contenedores. Nginx sirve Angular y reenvía `/api/*` y
`/health/*` a FastAPI en la red de Compose. FastAPI usa Cognito y el generador
PDF de `certificate-service`. El único puerto publicado es
`127.0.0.1:8000`.

## Archivos que utiliza la beta

| Ruta del equipo | Uso |
| --- | --- |
| `Backend/data/ucts_certificados.sqlite` | Catálogo de participantes y certificados que FastAPI abre en solo lectura. |
| `Backend/data/ucts_auth.sqlite` | Sesiones, desafíos, vínculos Cognito y auditoría de descargas. El directorio de datos se monta para conservar tanto la base como los archivos de transacción de SQLite. |
| `Backend/.env` | Región, User Pool, App Client y secretos del backend. Se lee al arrancar el contenedor. |
| `../certificate-service/app` y `../certificate-service/templates` | Código del generador durante la construcción y plantillas montadas en solo lectura durante el arranque. |
| `~/.aws` | Configuración y credenciales locales leídas en modo de solo lectura. El perfil predeterminado es `ucts-cert-lab`. |

Si usas otra ubicación, puedes exportar `BETA_CERTIFICATE_SERVICE_DIR`,
`BETA_DATA_DIR`, `BETA_BACKEND_ENV_FILE` o `BETA_AWS_DIR` con rutas absolutas.
Para otro perfil, exporta `BETA_AWS_PROFILE`. El perfil requiere permisos
`AdminGetUser` y `AdminCreateUser` sobre el User Pool. Las bases, las plantillas
y las credenciales permanecen en el equipo.

## Construir y arrancar

1. Abre Docker Desktop.
2. Detén el proceso que ocupe el puerto 8000 con `Ctrl+C` en su terminal.
3. Desde la raíz del proyecto, ejecuta:

   ```bash
   export BETA_UID="$(id -u)" BETA_GID="$(id -g)"
   docker compose -f compose.beta.yaml up --build -d
   docker compose -f compose.beta.yaml logs -f
   ```

Los identificadores del usuario permiten que FastAPI escriba en los archivos
existentes de SQLite conservando sus permisos. El arranque comprueba que ambos
archivos existan y prepara de forma idempotente las tablas de autenticación y
auditoría. Esta beta usa el origen local HTTP y una sola instancia de FastAPI
sobre SQLite.

Abre `http://127.0.0.1:8000/health/ready` para comprobar el backend y
`http://127.0.0.1:8000/certificados` para entrar al portal. Prueba con un correo
principal que controles. Tras descargar un certificado, consulta
`certificate_downloads` en la base de autenticación con DBeaver.

Si estás trabajando con `npm start`, Angular en el puerto `4200` también puede
iniciar sesión con la beta por medio de su proxy de desarrollo al puerto `8000`.
FastAPI admite únicamente los orígenes locales `localhost` y `127.0.0.1` en
ambos puertos.

Para detener los contenedores desde la raíz del proyecto:

```bash
docker compose -f compose.beta.yaml down
```

Los datos y la auditoría persisten en `Backend/data/`. El Compose de PostgreSQL
vive en `Backend/compose.yaml` y se ejecuta por separado.
