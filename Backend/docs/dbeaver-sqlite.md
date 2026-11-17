# Certificados UCTS en SQLite

La base local está en `Backend/data/ucts_certificados.sqlite`. Contiene participantes y asociaciones de certificados del Excel.

## Abrir en DBeaver

1. Selecciona **Nueva conexión** y el controlador **SQLite**. Acepta la descarga del controlador si DBeaver la solicita.
2. En **Path**, selecciona el archivo existente:

   ```text
   /Users/jonathancamposlozano/Documents/UCTS/Sistema_certificados_0.2/Backend/data/ucts_certificados.sqlite
   ```

3. En los ajustes de la conexión, abre **Initialization → Bootstrap queries**. Agrega `PRAGMA foreign_keys = ON;` para que se ejecute cada vez que DBeaver abre una conexión. Si ya estabas conectado, desconecta y vuelve a conectar.
4. Prueba la conexión. En el editor SQL ejecuta `PRAGMA foreign_keys;` y confirma que devuelve `1`. Abre las vistas `certificados_detalle` y `correos_con_principal` desde el navegador de bases de datos.

[Controlador SQLite en DBeaver](https://dbeaver.com/docs/dbeaver/Database-driver-SQLite/) · [Ajustes de inicialización](https://dbeaver.com/docs/dbeaver/Configure-Connection-Initialization-Settings/)

## Revisar filas pendientes

```sql
SELECT i.archivo, f.sha256, f.hoja, f.fila, f.motivo
FROM importacion_filas AS f
JOIN importaciones AS i USING (sha256)
WHERE f.motivo IS NOT NULL
ORDER BY i.fecha_utc, f.hoja, f.fila;
```

`importacion_filas` enlaza cada fila con los registros que pudieron asociarse. Una fila pendiente puede estar vinculada a un usuario o una plantilla reconocidos aunque su correo o certificado esté pendiente. Corrige las filas en el Excel y vuelve a importar. Cada archivo con un hash nuevo conserva su propia trazabilidad. Las revisiones agregan asociaciones válidas y preservan los UUID existentes. Los conflictos con nombres o principales existentes se registran para revisión. Las filas que desaparecen del Excel en una revisión conservan sus asociaciones previas en la base.

Para cambiar el principal de un usuario, actualiza `usuarios.correo_principal_id` con el UUID de otro correo del mismo usuario. Para agregar el primer correo o eliminar el último, agrupa la modificación de `correos` y la actualización de `correo_principal_id` en una misma transacción. SQLite comprueba ambas relaciones al confirmar.

## Crear o volver a cargar

Desde `Backend`, con las dependencias del proyecto instaladas y SQLite 3.37 o posterior:

```bash
umask 077
.venv/bin/python sqlite/importar.py ~/Downloads/'Data Process UCTS Certificados.xlsx'
.venv/bin/python -m unittest discover -s sqlite -v
```

El importador usa `sqlite/esquema.sql` y valida el libro antes de abrir la base. Reutiliza el esquema compatible, rechaza una base ajena y registra cada carga por SHA-256. El directorio `data/` está excluido de Git y la base contiene datos personales.
