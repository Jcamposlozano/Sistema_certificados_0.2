from datetime import date
from io import BytesIO

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ucts.adapters.documents.s3 import S3CertificateStore
from ucts.adapters.persistence.certificate_import import import_certificates, read_workbook
from ucts.adapters.persistence.certificate_publish import publish_certificates
from ucts.adapters.persistence.models import CertificateRow, CertificateSourceRow
from ucts.main import create_app

from .conftest import login

BUCKET = "private-ucts-test"
KEY = "certificates/test.pdf"
VERSION = "version-1"
PDF = b"%PDF-1.4\ncertificate\n%%EOF"


@pytest.fixture
def catalog(engine, tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Unificado"
    sheet.append(
        [
            "FECHA",
            "nombre",
            "CORREO",
            "template_id",
            "identificacion",
            "tipo_asistencia",
            "nombre_taller",
        ]
    )
    for day, name, email, document, role in (
        (1, "Ana", " ANA@example.com ", 123, "Asistente"),
        (2, "Ana", "ana@example.com", 123, "Asistente"),
        (1, "Ana", "ana@example.com", 123, "Ponente"),
        (1, "Bea", "bea@example.com", 456, "Asistente"),
        (1, "Compartido A", "shared@example.com", 789, "Asistente"),
        (1, "Compartido B", "shared@example.com", 980, "Asistente"),
        (1, "Correo inválido", 123, 123, "Asistente"),
    ):
        sheet.append([date(2026, 9, day), name, email, "simposio-IV", document, role, "Simposio"])
    for sheet_name, role_column, role, template in (
        ("Posters", "tipo_asistencia", "Ponente", "Poster"),
        ("Ganadores poster", "lugar", "Primer lugar", "Poster Ganador"),
    ):
        sheet = workbook.create_sheet(sheet_name)
        sheet.append(
            ["FECHA", "nombre", "CORREO", "template_id", "nombre_poster", "autores", role_column]
        )
        sheet.append([date(2026, 9, 1), "Ana", "ana@example.com", template, "Póster", "Ana", role])
    path = tmp_path / "Datos.xlsx"
    workbook.save(path)
    checksum, records, issues = read_workbook(path)
    assert len(issues) == 3
    assert {source.email for source in records} == {"ana@example.com", "bea@example.com"}
    with Session(engine) as db, db.begin():
        assert import_certificates(db, checksum, records)
    with Session(engine) as db, db.begin():
        assert not import_certificates(db, checksum, records)
        assert db.scalar(select(func.count()).select_from(CertificateSourceRow)) == 6
        assert db.scalar(select(func.count()).select_from(CertificateRow)) == 5
    return checksum


def test_pdf_catalog_enforces_owner_state_and_exact_s3_version(
    engine, settings, catalog, tmp_path, caplog
):
    s3 = boto3.client(
        "s3", region_name="us-east-1", aws_access_key_id="testing", aws_secret_access_key="testing"
    )
    store = S3CertificateStore(s3, BUCKET)
    manifest = tmp_path / "manifest.csv"
    headers = "hoja,fila_excel,correo,s3_key\n"
    manifest.write_text(
        headers + f"Unificado,2,ana@example.com,{KEY}\nUnificado,5,bea@example.com,{KEY}\n"
    )
    with pytest.raises(ValueError, match="objeto asignado"), Session(engine) as db, db.begin():
        publish_certificates(db, catalog, manifest, BUCKET, store.inspect)

    manifest.write_text(
        headers + f"Unificado,2,ana@example.com,{KEY}\nUnificado,3,ana@example.com,{KEY}\n"
    )
    with Stubber(s3) as stub:
        stub.add_response(
            "head_object",
            {"ContentLength": len(PDF), "VersionId": VERSION},
            {"Bucket": BUCKET, "Key": KEY},
        )
        with Session(engine) as db, db.begin():
            assert publish_certificates(db, catalog, manifest, BUCKET, store.inspect) == 1
        with Session(engine) as db, db.begin():
            assert publish_certificates(db, catalog, manifest, BUCKET, store.inspect) == 0
        stub.add_response(
            "get_object",
            {"ContentLength": len(PDF), "Body": StreamingBody(BytesIO(PDF), len(PDF))},
            {"Bucket": BUCKET, "Key": KEY, "VersionId": VERSION},
        )
        with TestClient(create_app(settings, engine=engine, certificate_store=store)) as client:
            assert client.get("/api/me/certificates").status_code == 401
            login(client, caplog)
            listing = client.get("/api/me/certificates").json()
            assert len(listing) == 4
            ready = next(cert for cert in listing if cert["available"])
            pending = next(cert for cert in listing if not cert["available"])
            url = f"/api/me/certificates/{ready['id']}"
            response = client.get(url)
            assert response.content == PDF
            assert response.headers["cache-control"] == "no-store"
            assert "s3" not in ready and "s3_key" not in ready
            assert client.get(f"/api/me/certificates/{pending['id']}").status_code == 403
            login(client, caplog, email="bea@example.com")
            assert client.get(url).status_code == 404
        stub.assert_no_pending_responses()
