import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID, uuid4

from importar import (
    DEFAULT_DB,
    TABLES,
    ImportValidationError,
    check_integrity,
    connect,
    import_workbook,
    load_records,
)
from openpyxl import Workbook, load_workbook


class IntegridadSQLite(unittest.TestCase):
    def setUp(self):
        sandbox = TemporaryDirectory(dir=DEFAULT_DB.parent, prefix=".prueba-sqlite-")
        self.addCleanup(sandbox.cleanup)
        directory = Path(sandbox.name)
        self.excel = directory / "sintetico.xlsx"
        self.database = directory / "sintetico.sqlite"
        self.make_excel()

    def make_excel(self, extra=False):
        with closing(Workbook()) as book:
            users = book.active
            users.title = "Usuarios"
            users.append(("nombre", "identificacion"))
            users.append(("Persona Sintética", "0007"))
            users.append(("Persona Sintética", "8"))
            users.append(("Marcador de prueba", "9"))
            if extra:
                users.append(("Registro adicional", "10"))
            emails = book.create_sheet("Correos")
            for row in (
                ("identificacion", "CORREO", "Principal"),
                (7, "uno@example.org", "TRUE"),
                ("0007", "dos@example.org", "FALSE"),
                ("0007", "UNO@example.org", True),
                ("8", "uno@example.org", True),
                ("9", "tres@example.org", False),
                ("123", "cuatro@example.org", True),
            ):
                emails.append(row)
            emails["A2"].number_format = "0000"
            certificates = book.create_sheet("Certificados")
            for row in (
                ("template_id", "nombre_taller", "identificacion", "tipo_asistencia"),
                ("proveedor", "Taller A", "0007", "A"),
                ("proveedor", "Taller A", "0007", "B"),
                ("proveedor", "Taller B", "0007", "A"),
                ("proveedor", "Taller B", "9", "A"),
                ("proveedor", "Taller A", "0007", "A"),
                ("proveedor", "Taller C", "123", "B"),
            ):
                certificates.append(row)
            templates = book.create_sheet("Templates")
            templates.append(("template_id", "nombre_taller"))
            templates.append(("proveedor", "Taller A"))
            templates.append(("proveedor", "Taller sin respaldo"))
            book.save(self.excel)

    def snapshots(self):
        with closing(connect(self.database)) as db:
            return [
                db.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall() for table in TABLES
            ]

    def test_cruces_trazabilidad_duplicados_y_ceros(self):
        checksum, repeated, counts, pending = import_workbook(self.excel, self.database)
        self.assertFalse(repeated)
        self.assertEqual(tuple(counts.values()), (1, 3, 3, 3, 4, 1, 17))
        self.assertEqual(
            {(sheet, number) for sheet, number, _ in pending},
            {("Certificados", 7), ("Correos", 6), ("Correos", 7), ("Templates", 3)},
        )
        with closing(connect(self.database)) as db:
            check_integrity(db)
            self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone(), (1,))
            self.assertEqual(
                db.execute("SELECT count(*) FROM certificados_detalle").fetchone(), (4,)
            )
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM certificados_detalle WHERE identificacion = '9'"
                ).fetchone(),
                (1,),
            )
            self.assertEqual(
                db.execute(
                    "SELECT count(DISTINCT correo_id) FROM importacion_filas "
                    "WHERE hoja = 'Correos' AND fila IN (2, 4)"
                ).fetchone(),
                (1,),
            )
            self.assertEqual(
                db.execute("SELECT sha256, archivo FROM importaciones").fetchone(),
                (checksum, self.excel.name),
            )
            self.assertEqual(
                db.execute(
                    "SELECT DISTINCT identificacion FROM correos_con_principal "
                    "ORDER BY identificacion"
                ).fetchall(),
                [("0007",), ("8",)],
            )
            for table in TABLES[:5]:
                for (key,) in db.execute(f"SELECT id FROM {table}"):
                    self.assertEqual(UUID(key).version, 4)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "INSERT INTO usuarios (id, identificacion, nombre_completo) "
                    "VALUES ('malformado', '11', 'Marcador')"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "INSERT INTO certificados "
                    "SELECT ?, usuario_id, evento_id, template_uuid, tipo_asistencia "
                    "FROM certificados LIMIT 1",
                    (str(uuid4()),),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "INSERT INTO correos (id, usuario_id, direccion) "
                    "SELECT ?, usuario_id, upper(direccion) FROM correos LIMIT 1",
                    (str(uuid4()),),
                )

    def test_cambio_de_principal_y_rechazo_al_confirmar(self):
        import_workbook(self.excel, self.database)
        with closing(connect(self.database)) as db:
            user_id = db.execute(
                "SELECT id FROM usuarios WHERE identificacion = '0007'"
            ).fetchone()[0]
            secondary = db.execute(
                "SELECT id FROM correos WHERE usuario_id = ? AND direccion = 'dos@example.org'",
                (user_id,),
            ).fetchone()[0]
            db.execute(
                "UPDATE usuarios SET correo_principal_id = ? WHERE id = ?", (secondary, user_id)
            )
            self.assertEqual(
                db.execute(
                    "SELECT correo_id FROM correos_con_principal "
                    "WHERE usuario_id = ? AND principal = 1",
                    (user_id,),
                ).fetchall(),
                [(secondary,)],
            )
            other = db.execute(
                "SELECT usuario_id, correo_id FROM correos_con_principal WHERE identificacion = '8'"
            ).fetchone()
            for value in (None, other[1]):
                db.execute("BEGIN")
                db.execute(
                    "UPDATE usuarios SET correo_principal_id = ? WHERE id = ?", (value, user_id)
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    db.commit()
                db.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM correos WHERE id = ?", (secondary,))
            db.execute("BEGIN")
            no_mail = db.execute("SELECT id FROM usuarios WHERE identificacion = '9'").fetchone()[0]
            db.execute(
                "INSERT INTO correos (id, usuario_id, direccion) VALUES (?, ?, ?)",
                (str(uuid4()), no_mail, "sin-principal@example.org"),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                db.commit()
            db.rollback()

            db.execute("BEGIN")
            db.execute("DELETE FROM correos WHERE usuario_id = ?", (user_id,))
            db.execute("UPDATE usuarios SET correo_principal_id = NULL WHERE id = ?", (user_id,))
            db.commit()
            check_integrity(db)

    def test_template_de_otro_evento(self):
        import_workbook(self.excel, self.database)
        with closing(connect(self.database)) as db:
            other = str(uuid4())
            db.execute("INSERT INTO evento_head VALUES (?, 'evento2', 'evento2')", (other,))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "INSERT INTO certificados "
                    "SELECT ?, usuario_id, ?, template_uuid, tipo_asistencia "
                    "FROM certificados LIMIT 1",
                    (str(uuid4()), other),
                )
            check_integrity(db)

    def test_repetir_archivo_y_reutilizar_uuid_en_otra_revision(self):
        import_workbook(self.excel, self.database)
        original = self.snapshots()
        self.assertTrue(import_workbook(self.excel, self.database)[1])
        self.assertEqual(original, self.snapshots())

        self.make_excel(extra=True)
        self.assertFalse(import_workbook(self.excel, self.database)[1])
        current = self.snapshots()
        for index in range(5):
            self.assertTrue(set(original[index]) <= set(current[index]))
        self.assertEqual(len(current[1]), 4)

    def test_rollback_de_datos_y_esquema(self):
        def fail_after_load(*args):
            load_records(*args)
            args[0].execute("INSERT INTO evento_head VALUES ('incorrecto', 'otro', 'otro')")

        with patch("importar.load_records", side_effect=fail_after_load):
            with self.assertRaises(sqlite3.IntegrityError):
                import_workbook(self.excel, self.database)
        with closing(connect(self.database)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sqlite_schema").fetchone(), (0,))
            self.assertEqual(db.execute("PRAGMA user_version").fetchone(), (0,))

        import_workbook(self.excel, self.database)
        original = self.snapshots()
        self.make_excel(extra=True)
        with patch("importar.load_records", side_effect=fail_after_load):
            with self.assertRaises(sqlite3.IntegrityError):
                import_workbook(self.excel, self.database)
        self.assertEqual(original, self.snapshots())

    def test_rechaza_base_ajena(self):
        with closing(connect(self.database)) as db:
            db.execute("CREATE TABLE legado (dato TEXT)")
            db.execute("INSERT INTO legado VALUES ('sintético')")
        original = self.database.read_bytes()
        with self.assertRaises(ImportValidationError):
            import_workbook(self.excel, self.database)
        self.assertEqual(self.database.read_bytes(), original)

    def test_grupos_ambiguos_y_proteccion_del_principal_existente(self):
        import_workbook(self.excel, self.database)

        with closing(load_workbook(self.excel)) as book:
            book["Correos"]["C2"] = False
            book["Correos"]["C3"] = True
            book["Correos"].delete_rows(4)
            book["Correos"].append(("9", "distinto@example.org", True))
            book["Correos"].append(("9", "tercero@example.org", True))
            book.save(self.excel)
        _, _, counts, pending = import_workbook(self.excel, self.database)
        issues = [reason for sheet, _, reason in pending if sheet == "Correos"]
        self.assertEqual(
            issues.count("principal en conflicto con el correo principal existente"), 2
        )
        self.assertEqual(issues.count("más de un correo marcado como principal"), 3)
        self.assertEqual(counts["correos"], 3)
        self.assertEqual(counts["certificados"], 4)


if __name__ == "__main__":
    unittest.main()
