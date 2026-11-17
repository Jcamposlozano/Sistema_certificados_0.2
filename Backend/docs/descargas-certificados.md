# Generación y auditoría de certificados UCTS

FastAPI importa el generador PDF de `certificate-service` dentro de su propio
proceso. Las plantillas se leen de `Backend/templates` por defecto. Angular mantiene el proxy a `127.0.0.1:8000` y descarga por
`GET /api/me/certificates/{id}`. La sesión determina el titular. FastAPI obtiene
el nombre, la identificación, el tipo de asistencia, el taller y el ID de
plantilla desde el catálogo, y los entrega al generador. Los certificados de
plantillas sin los datos requeridos se muestran como pendientes.

## Ejecutar en un solo puerto

Desde `Backend`, instala el extra con `poetry install -E generator`. En macOS
se requieren las bibliotecas nativas de WeasyPrint (Pango y HarfBuzz). Con el
`.env` de Cognito configurado, ejecuta una vez:

```bash
umask 077
CERTIFICATE_CATALOG_SQLITE=data/ucts_certificados.sqlite \
DATABASE_URL=sqlite:///data/ucts_auth.sqlite \
.venv/bin/ucts init-catalog-auth
```

Cuando estés listo para el cambio, detén el `make run` de `certificate-service`
en su terminal. Arranca el backend integrado en el mismo puerto:

```bash
AWS_PROFILE=ucts-cert-lab \
CERTIFICATE_CATALOG_SQLITE=data/ucts_certificados.sqlite \
DATABASE_URL=sqlite:///data/ucts_auth.sqlite \
CERTIFICATE_GENERATOR_ENABLED=true \
DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix)/lib" \
.venv/bin/uvicorn \
  --app-dir /Users/jonathancamposlozano/Documents/UCTS/certificate-service \
  ucts.main:create_app --factory --host 127.0.0.1 --port 8000
```

En Linux omite la variable `DYLD_FALLBACK_LIBRARY_PATH`. Verifica
`http://127.0.0.1:8000/health/ready` y abre el portal Angular. Esta entrada
expone la descarga autenticada del portal. La API independiente
`/certifications/v1/certificates/generate` pertenece a `make run` del otro
proyecto y queda fuera del servidor integrado.

## Consultar la auditoría

Abre `Backend/data/ucts_auth.sqlite` en DBeaver y consulta:

```sql
SELECT downloaded_at_utc,
       datetime(downloaded_at_utc, '-5 hours') AS fecha_hora_bogota,
       participant_id,
       certificate_id,
       event_id
FROM certificate_downloads
ORDER BY downloaded_at_utc DESC;
```

Cada fila guarda el UUID del participante, el del certificado y el del evento.
El UUID del participante se cruza con `usuarios.id` del catálogo en caso de
necesitar el nombre. Para la antigua descarga de demostración por evento,
`certificate_id` queda vacío y el evento identifica el documento. La auditoría
se registra después de preparar un PDF válido para la respuesta. Mide las
descargas atendidas por FastAPI. El navegador decide si guarda el archivo.
Un PDF que se vuelve a descargar genera otra fila. Los errores de generación y
los accesos rechazados quedan fuera de la tabla.

Con una base de estado PostgreSQL, aplica la migración local
`0003_certificate_downloads` mediante Alembic antes de activar la descarga.
