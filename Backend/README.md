# UCTS Zone · API

API REST con FastAPI, Python 3.12+, arquitectura hexagonal, PostgreSQL y autenticación OTP por correo mediante Amazon Cognito. Poetry administra todas las dependencias; no usar pip ni requirements.txt para este proyecto.

## Inicio local

Requisitos: Poetry 2, Python 3.12+ y Docker con Compose.

Desde `Backend`:

```sh
poetry env use /opt/homebrew/bin/python3.12
poetry install
cp .env.example .env
# Ajusta .env si ya tienes uno. Nunca sobrescribas credenciales propias.
docker compose up -d db
poetry run alembic upgrade head
poetry run ucts seed
poetry run uvicorn ucts.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

`poetry.lock` fija las versiones. `poetry.toml` coloca el entorno virtual en `Backend/.venv`.

- Swagger: http://localhost:8000/docs
- OpenAPI: http://localhost:8000/openapi.json
- Estado: `/health/live` y `/health/ready`
- PostgreSQL local: `localhost:5433/ucts_zone`

La configuración de ejemplo habilita **AUTH_MODE=local**. El OTP es aleatorio, vence a los 180 segundos y se muestra únicamente en la terminal de la API. No se envían correos en modo local. El usuario de ejemplo es `demo@ucts.local`. El PDF local tiene una marca de demostración.

El frontend continúa en su modo demo independiente; su conexión HTTP con esta API queda para el siguiente paso. Los endpoints corresponden al contrato planteado, con fechas ISO `YYYY-MM-DD`. No se usa el código fijo 123456 en este backend.

## Arquitectura

```text
src/ucts/
  domain/                 Entidades y errores, sin dependencias de frameworks
  application/
    ports.py              Contratos de identidad, repositorio, transacción y PDF
    services.py           Casos de uso OTP, sesión, eventos y descarga
  adapters/
    http/                 Rutas y validaciones FastAPI
    persistence/          SQLAlchemy + psycopg; PostgreSQL
    identity/             Adaptadores Cognito y local
    documents/            Generación PDF con ReportLab
  config.py               Configuración validada desde variables de entorno
  main.py                 Composición e inyección de adaptadores
  cli.py                  Seed local y limpieza de registros vencidos
migrations/               Historial de esquema Alembic
```

La aplicación utiliza puertos; los adaptadores dependen de esos contratos y del dominio. Ninguna regla de autenticación o habilitación depende de FastAPI. Cambiar PostgreSQL, Cognito o el generador PDF requiere sustituir un adaptador.

## Endpoints

| Método | Ruta | Comportamiento |
| --- | --- | --- |
| POST | `/api/auth/otp/request` | `{ "email": "demo@ucts.local" }` → `challengeId`, `expiresIn`, `resendAfter` y mensaje genérico. |
| POST | `/api/auth/otp/verify` | `{ "challengeId": "...", "code": "..." }` → 204 y cookie de sesión HttpOnly. |
| POST | `/api/auth/logout` | Revoca la sesión en servidor y elimina la cookie. |
| GET | `/api/me` | Perfil de la sesión activa. |
| GET | `/api/me/events` | Solo las participaciones del usuario autenticado. |
| GET | `/api/me/events/{id}/certificate` | PDF como archivo adjunto si el certificado está habilitado. |

Todas las peticiones POST requieren `Origin` de la lista `ALLOWED_ORIGINS`, incluso desde curl/Insomnia. Swagger funciona entrando desde un origen permitido (`http://localhost:8000`). Angular usará `withCredentials: true`. CORS no usa comodines. Localmente usar `localhost` tanto en Angular como en la API; no mezclar con `127.0.0.1` por las cookies.

Ejemplo de petición local:

```sh
curl -X POST http://localhost:8000/api/auth/otp/request \
  -H 'Origin: http://localhost:4200' -H 'Content-Type: application/json' \
  -d '{"email":"demo@ucts.local"}'
```

Errores: 401 sin sesión o OTP inválido/vencido; 403 origen o certificado no permitido; 404 evento ajeno/inexistente; 422 formato inválido; 429 límite de solicitudes; 503 dependencia no disponible. La API no revela si un evento existe para otra persona.

## PostgreSQL y DBeaver

Ver [guía de conexión](docs/dbeaver.md). La base y las tablas las crean PostgreSQL y Alembic; DBeaver permite consultarlas y administrarlas. Incluimos un proyecto de conexión importable en `dbeaver/UCTS` sin contraseña guardada.

Entidades: `participants` (correo único, identidad Cognito `sub`), `events`, `attendances` (participación y habilitación), `otp_challenges`, `auth_sessions`, `rate_limits`. Horas positivas, claves foráneas y participación única por persona/evento. Los timestamps de autenticación son segundos Unix UTC.

Migraciones nuevas:

```sh
poetry run alembic revision --autogenerate -m "describe el cambio"
# Revisa la migración antes de aplicarla.
poetry run alembic upgrade head
poetry run alembic check
```

No se ejecuta `create_all` al iniciar la API. El seed es explícito, idempotente y está bloqueado fuera del modo local.

## Cognito real

Ver [configuración de AWS](docs/cognito.md). Para activar el conector:

```dotenv
AUTH_MODE=cognito
AWS_REGION=us-east-1
COGNITO_CLIENT_ID=tu_app_client_id
COGNITO_CLIENT_SECRET=solo_si_existe
```

En producción usar `APP_ENV=production`, `COOKIE_SECURE=true`, orígenes HTTPS explícitos y un `OTP_SECRET` aleatorio. No guardar secretos en Git. La configuración rechaza el adaptador local en producción.

## Controles implementados

- OTP local guardado como HMAC con salt; jamás se devuelve en respuestas HTTP.
- Cognito administra y envía el OTP real con `USER_AUTH` / `EMAIL_OTP`.
- Desafío opaco, con caducidad, máximo cinco intentos y consumo único bajo bloqueo de fila.
- Reenvío invalida desafíos anteriores. Límites compartidos en PostgreSQL: un envío por correo cada 60 s, 10 por hora y 20 por IP cada 15 min.
- Sesión opaca de una hora guardada como hash, revocable mediante logout; no se exponen tokens AWS al navegador.
- Identidad real validada por Cognito con `get_user`; se exige correo verificado y se vincula el `sub` al registro de participante.
- Cookie HttpOnly y SameSite=Lax, Secure en producción, validación de Origin para POST, hosts permitidos y respuestas privadas sin caché.
- Consulta de participación y habilitación en servidor antes de generar PDF.

Para producción: desplegar frontend y API bajo el mismo sitio (preferiblemente `/api` por proxy), TLS, base de datos privada y secretos administrados. Si hay proxy inverso, configurar Uvicorn para confiar en las cabeceras de IP únicamente de ese proxy; no confiar en IPs reenviadas por clientes arbitrarios. Limitar tamaño/tasa de solicitudes también en el proxy. La sesión de esta API es independiente tras el login: un cierre global en Cognito no revoca automáticamente estas sesiones; logout de esta API sí las revoca.

Programar la limpieza de registros temporales:

```sh
poetry run ucts cleanup
```

No se incluye todavía administración de eventos/participantes, carga masiva, alta de usuarios Cognito, revocación administrativa global ni diseño institucional definitivo de certificados.

## Pruebas

```sh
poetry run ruff check .
poetry run pytest -q
```

Las pruebas rápidas usan SQLite en memoria y un proveedor OTP local. Las pruebas del adaptador AWS usan Stubber, sin conexión a Cognito ni envío de correo.

Para comprobar PostgreSQL y bloqueos concurrentes se necesita una base **exclusiva de pruebas**, nunca `ucts_zone`:

```sh
docker compose exec db createdb -U ucts ucts_zone_test
TEST_DATABASE_URL=postgresql+psycopg://ucts:ucts_local_only@localhost:5433/ucts_zone_test \
  poetry run pytest -q
```

Las pruebas crean y eliminan tablas en esa base. Incluyen acceso, expiración, intentos fallidos, reenvío, consumo único, revocación, aislamiento de eventos, PDF, CORS y validación de configuración.
