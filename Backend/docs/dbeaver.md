# PostgreSQL en DBeaver

PostgreSQL corre en Docker; DBeaver usa su controlador JDBC PostgreSQL, mientras Python usa psycopg 3 mediante SQLAlchemy. Son conectores diferentes hacia la misma base.

## Conexión manual

1. Inicia la base con `docker compose up -d db` desde Backend.
2. En DBeaver selecciona **Nueva conexión → PostgreSQL**.
3. Completa estos valores:

| Campo | Valor local |
| --- | --- |
| Host | localhost |
| Puerto | 5433 |
| Base de datos | ucts_zone |
| Usuario | ucts |
| Contraseña | ucts_local_only |
| URL JDBC | jdbc:postgresql://localhost:5433/ucts_zone |

4. Pulsa **Probar conexión**. Si DBeaver pide el controlador PostgreSQL, permite descargarlo.
5. Guarda como **UCTS Zone · Local**.
6. Ejecuta `poetry run alembic upgrade head`; refresca **Schemas → public → Tables**.
7. Ejecuta `poetry run ucts import-certificates` para cargar el [catálogo](certificate-catalog.md).

Estas credenciales corresponden únicamente al contenedor local. El puerto está publicado solo en 127.0.0.1. El volumen `ucts_postgres_data` conserva los datos al detenerlo. `docker compose down` lo detiene; no uses `down -v` si necesitas conservar los datos.

## Proyecto incluido

Puedes importar `Backend/dbeaver/UCTS` desde **Archivo → Importar → General → Proyectos existentes en el espacio de trabajo**. Incluye `.project`, `.dbeaver/data-sources.json` y una consulta de validación en `Scripts`. Si tu edición no permite esa importación, usa la conexión manual anterior. Al conectar introduce la contraseña local; no hay contraseñas guardadas en el proyecto.

## Verificación

```sql
SELECT current_database(), current_user, version();
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' ORDER BY table_name;

SELECT status, count(*) FROM certificates GROUP BY status ORDER BY status;

SELECT sheet, count(*) FROM certificate_sources GROUP BY sheet ORDER BY sheet;
```

No compartas ni exportes las tablas temporales de autenticación. Usa nuevas credenciales, roles con permisos mínimos y una base separada para producción.

Referencias oficiales: https://dbeaver.com/docs/dbeaver/Create-Connection/ y https://dbeaver.com/docs/dbeaver/Data-Sources-Json-Reference/
