# UCTS Zone · API

API REST con FastAPI, Python 3.12+, arquitectura hexagonal, PostgreSQL y autenticación OTP por correo mediante Amazon Cognito. Poetry administra todas las dependencias; no usar pip ni requirements.txt para este proyecto.

## Acceso con correo principal y Cognito

Sigue la [guía de Cognito y SES](docs/cognito.md) para conectar Angular con FastAPI
y autorizar el acceso desde `correos_con_principal` del catálogo SQLite importado.
El catálogo se abre en solo lectura. El estado de autenticación se inicializa en
un archivo SQLite separado para el piloto.

## Inicio local con el catálogo PostgreSQL

Requisitos: Poetry 2, Python 3.12+ y Docker con Compose.

Desde `Backend`:

```sh
poetry env use python3
poetry install
cp .env.example .env
# Ajusta .env si ya tienes uno. Nunca sobrescribas credenciales propias.
docker compose up -d db
poetry run alembic upgrade head
poetry run ucts import-certificates
poetry run uvicorn ucts.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

`poetry.lock` fija las versiones. `poetry.toml` coloca el entorno virtual en `Backend/.venv`.

- Swagger: http://localhost:8000/docs
- OpenAPI: http://localhost:8000/openapi.json
- Estado: `/health/live` y `/health/ready`
- PostgreSQL local: `localhost:5433/ucts_zone`

La configuración de ejemplo habilita **AUTH_MODE=local**. El OTP es aleatorio, vence a los 180 segundos y se muestra únicamente en la terminal de la API. No se envían correos en modo local. Para probar con datos ficticios, ejecuta `poetry run ucts seed` y usa `demo@example.com`. El PDF de ejemplo tiene una marca de demostración.

El frontend llama a esta API mediante el proxy de desarrollo de Angular.

## Arquitectura

```text
src/ucts/
  domain/                 Entidades y errores, sin dependencias de frameworks
  application/
    ports.py              Contratos de identidad, repositorio, transacción y PDF
    services.py           Casos de uso OTP, sesión, eventos y descarga
  adapters/
    http/                 Rutas y validaciones FastAPI
    persistence/          Estado SQLAlchemy y catálogo SQLite de solo lectura
    identity/             Adaptadores Cognito y local
    documents/            Descarga privada S3 y PDF de demostración
  config.py               Configuración validada desde variables de entorno
  main.py                 Composición e inyección de adaptadores
  cli.py                  Alta Cognito, inicialización de sesiones y administración de datos
migrations/               Historial de esquema Alembic
```

La aplicación utiliza puertos; los adaptadores dependen de esos contratos y del dominio. Ninguna regla de autenticación o habilitación depende de FastAPI. PostgreSQL, Cognito y S3 se integran mediante adaptadores.

## Endpoints

| Método | Ruta | Comportamiento |
| --- | --- | --- |
| POST | `/api/auth/otp/request` | `{ "email": "demo@example.com" }` → `challengeId`, `expiresIn`, `resendAfter` y mensaje genérico. |
| POST | `/api/auth/otp/verify` | `{ "challengeId": "...", "code": "..." }` → 204 y cookie de sesión HttpOnly. |
| POST | `/api/auth/logout` | Revoca la sesión en servidor y elimina la cookie. |
| GET | `/api/me` | Perfil de la sesión activa. |
| GET | `/api/me/events` | Solo las participaciones del usuario autenticado. |
| GET | `/api/me/events/{id}/certificate` | PDF de demostración habilitado en modo local. |
| GET | `/api/me/certificates` | Catálogo de certificados del titular, con su disponibilidad. |
| GET | `/api/me/certificates/{id}` | Descarga del PDF publicado en S3. |

Todas las peticiones POST requieren `Origin` de la lista `ALLOWED_ORIGINS`, incluso desde curl/Insomnia. Swagger funciona entrando desde un origen permitido (`http://localhost:8000`). Angular usa rutas relativas bajo el mismo origen visible al navegador. Localmente abre el portal en `http://localhost:4200`.

Ejemplo de petición local:

```sh
curl -X POST http://localhost:8000/api/auth/otp/request \
  -H 'Origin: http://localhost:4200' -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com"}'
```

Errores: 401 sin sesión o OTP inválido/vencido; 403 origen o certificado no permitido; 404 evento ajeno/inexistente; 422 formato inválido; 429 límite de solicitudes; 503 dependencia no disponible. La API no revela si un evento existe para otra persona.

## PostgreSQL y DBeaver

Ver [guía de conexión](docs/dbeaver.md). La base y las tablas las crean PostgreSQL y Alembic; DBeaver permite consultarlas y administrarlas. Incluimos un proyecto de conexión importable en `dbeaver/UCTS` sin contraseña guardada.

El [catálogo de certificados](docs/certificate-catalog.md) describe el modelo relacional, la carga desde Excel, las incidencias del archivo y cómo vincular PDFs en S3.

Migraciones nuevas:

```sh
poetry run alembic revision --autogenerate -m "describe el cambio"
# Revisa la migración antes de aplicarla.
poetry run alembic upgrade head
poetry run alembic check
```

No se ejecuta `create_all` al iniciar la API. El seed es explícito, idempotente y está bloqueado fuera del modo local.

## Controles implementados

- OTP local guardado como HMAC con salt; jamás se devuelve en respuestas HTTP.
- Cognito administra y envía el OTP real con `USER_AUTH` / `EMAIL_OTP`.
- Desafío opaco, con caducidad, máximo cinco intentos y consumo único con bloqueo de fila en PostgreSQL y transacción inmediata en el piloto SQLite.
- Reenvío invalida desafíos anteriores. Límites persistentes: un envío por correo cada 60 s, 10 por hora y 20 por IP cada 15 min.
- Sesión opaca de una hora guardada como hash, revocable mediante logout; no se exponen tokens AWS al navegador.
- Identidad real validada por Cognito con `get_user`; se exige correo verificado y se vincula el `sub` al registro de participante.
- Cookie HttpOnly y SameSite=Lax, Secure en producción, validación de Origin para POST, hosts permitidos y respuestas privadas sin caché.
- El OTP requiere un correo principal único en el catálogo SQLite o un participante habilitado en PostgreSQL. La API verifica titular y publicación antes de descargar cada PDF.

Para producción: desplegar frontend y API bajo el mismo sitio (preferiblemente `/api` por proxy), TLS, base de datos privada y secretos administrados. Si hay proxy inverso, configurar Uvicorn para confiar en las cabeceras de IP únicamente de ese proxy; no confiar en IPs reenviadas por clientes arbitrarios. Limitar tamaño/tasa de solicitudes también en el proxy. La sesión de esta API es independiente tras el login: un cierre global en Cognito no revoca automáticamente estas sesiones; logout de esta API sí las revoca.

Programar la limpieza de registros temporales:

```sh
poetry run ucts cleanup
```

La carga masiva y la vinculación de PDFs se operan mediante la CLI. El alta en Cognito y la conexión de Angular son pasos separados.

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
