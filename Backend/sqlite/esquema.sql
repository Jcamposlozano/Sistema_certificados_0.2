PRAGMA foreign_keys = ON;
PRAGMA application_id = 1430471763;
PRAGMA user_version = 1;

CREATE TABLE evento_head (
    id TEXT PRIMARY KEY NOT NULL CHECK (
        length(id) = 36 AND instr(id, char(0)) = 0
        AND length(replace(id, '-', '')) = 32
        AND substr(id, 9, 1) = '-' AND substr(id, 14, 1) = '-'
        AND substr(id, 19, 1) = '-' AND substr(id, 24, 1) = '-'
        AND replace(id, '-', '') NOT GLOB '*[^0-9a-f]*'
    ),
    codigo TEXT NOT NULL UNIQUE CHECK (trim(codigo) <> ''),
    nombre TEXT NOT NULL CHECK (trim(nombre) <> '')
) STRICT;

CREATE TABLE usuarios (
    id TEXT PRIMARY KEY NOT NULL CHECK (
        length(id) = 36 AND instr(id, char(0)) = 0
        AND length(replace(id, '-', '')) = 32
        AND substr(id, 9, 1) = '-' AND substr(id, 14, 1) = '-'
        AND substr(id, 19, 1) = '-' AND substr(id, 24, 1) = '-'
        AND replace(id, '-', '') NOT GLOB '*[^0-9a-f]*'
    ),
    identificacion TEXT NOT NULL UNIQUE CHECK (trim(identificacion) <> ''),
    nombre_completo TEXT NOT NULL CHECK (trim(nombre_completo) <> ''),
    correo_principal_id TEXT,
    tiene_principal INTEGER GENERATED ALWAYS AS (correo_principal_id IS NOT NULL) STORED,
    UNIQUE (id, tiene_principal),
    FOREIGN KEY (id, correo_principal_id) REFERENCES correos (usuario_id, id)
        DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE correos (
    id TEXT PRIMARY KEY NOT NULL CHECK (
        length(id) = 36 AND instr(id, char(0)) = 0
        AND length(replace(id, '-', '')) = 32
        AND substr(id, 9, 1) = '-' AND substr(id, 14, 1) = '-'
        AND substr(id, 19, 1) = '-' AND substr(id, 24, 1) = '-'
        AND replace(id, '-', '') NOT GLOB '*[^0-9a-f]*'
    ),
    usuario_id TEXT NOT NULL,
    direccion TEXT NOT NULL COLLATE NOCASE CHECK (
        direccion = trim(direccion) AND instr(direccion, '@') > 1
        AND instr(direccion, '@') < length(direccion)
    ),
    requiere_principal INTEGER GENERATED ALWAYS AS (1) STORED,
    UNIQUE (usuario_id, direccion),
    UNIQUE (usuario_id, id),
    -- Todo correo exige un usuario con principal al confirmar la transacción.
    FOREIGN KEY (usuario_id, requiere_principal) REFERENCES usuarios (id, tiene_principal)
        DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE templates (
    id TEXT PRIMARY KEY NOT NULL CHECK (
        length(id) = 36 AND instr(id, char(0)) = 0
        AND length(replace(id, '-', '')) = 32
        AND substr(id, 9, 1) = '-' AND substr(id, 14, 1) = '-'
        AND substr(id, 19, 1) = '-' AND substr(id, 24, 1) = '-'
        AND replace(id, '-', '') NOT GLOB '*[^0-9a-f]*'
    ),
    evento_id TEXT NOT NULL REFERENCES evento_head (id),
    template_id TEXT NOT NULL CHECK (id <> template_id AND trim(template_id) <> ''),
    nombre_taller TEXT NOT NULL CHECK (trim(nombre_taller) <> ''),
    UNIQUE (evento_id, template_id, nombre_taller),
    UNIQUE (evento_id, id)
) STRICT;

CREATE TABLE certificados (
    id TEXT PRIMARY KEY NOT NULL CHECK (
        length(id) = 36 AND instr(id, char(0)) = 0
        AND length(replace(id, '-', '')) = 32
        AND substr(id, 9, 1) = '-' AND substr(id, 14, 1) = '-'
        AND substr(id, 19, 1) = '-' AND substr(id, 24, 1) = '-'
        AND replace(id, '-', '') NOT GLOB '*[^0-9a-f]*'
    ),
    usuario_id TEXT NOT NULL REFERENCES usuarios (id),
    evento_id TEXT NOT NULL REFERENCES evento_head (id),
    template_uuid TEXT NOT NULL,
    tipo_asistencia TEXT NOT NULL CHECK (trim(tipo_asistencia) <> ''),
    UNIQUE (usuario_id, evento_id, template_uuid, tipo_asistencia),
    FOREIGN KEY (evento_id, template_uuid) REFERENCES templates (evento_id, id)
) STRICT;

CREATE INDEX certificados_por_template ON certificados (evento_id, template_uuid);

CREATE TABLE importaciones (
    sha256 TEXT PRIMARY KEY NOT NULL CHECK (
        length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    archivo TEXT NOT NULL CHECK (trim(archivo) <> ''),
    fecha_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
) STRICT;

CREATE TABLE importacion_filas (
    sha256 TEXT NOT NULL REFERENCES importaciones (sha256),
    hoja TEXT NOT NULL CHECK (hoja IN ('Usuarios', 'Correos', 'Certificados', 'Templates')),
    fila INTEGER NOT NULL CHECK (fila >= 2),
    motivo TEXT CHECK (trim(motivo) <> ''),
    usuario_id TEXT REFERENCES usuarios (id) ON DELETE SET NULL,
    correo_id TEXT REFERENCES correos (id) ON DELETE SET NULL,
    certificado_id TEXT REFERENCES certificados (id) ON DELETE SET NULL,
    template_uuid TEXT REFERENCES templates (id) ON DELETE SET NULL,
    PRIMARY KEY (sha256, hoja, fila)
) STRICT;

CREATE INDEX importacion_filas_por_usuario ON importacion_filas (usuario_id);
CREATE INDEX importacion_filas_por_correo ON importacion_filas (correo_id);
CREATE INDEX importacion_filas_por_certificado ON importacion_filas (certificado_id);
CREATE INDEX importacion_filas_por_template ON importacion_filas (template_uuid);

CREATE VIEW certificados_detalle AS
SELECT c.id AS certificado_id, u.id AS usuario_id, u.identificacion, u.nombre_completo,
       e.id AS evento_id, e.codigo AS evento_codigo, e.nombre AS evento_nombre,
       t.id AS template_uuid, t.template_id, t.nombre_taller, c.tipo_asistencia
FROM certificados AS c
JOIN usuarios AS u ON u.id = c.usuario_id
JOIN evento_head AS e ON e.id = c.evento_id
JOIN templates AS t ON t.evento_id = c.evento_id AND t.id = c.template_uuid;

CREATE VIEW correos_con_principal AS
SELECT c.id AS correo_id, u.id AS usuario_id, u.identificacion, u.nombre_completo,
       c.direccion, c.id = u.correo_principal_id AS principal
FROM correos AS c
JOIN usuarios AS u ON u.id = c.usuario_id;
