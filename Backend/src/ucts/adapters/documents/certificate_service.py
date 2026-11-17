import logging

from ucts.adapters.documents.s3 import MAX_PDF_BYTES
from ucts.domain.models import AppError, Certificate, ErrorKind

logger = logging.getLogger(__name__)


class CertificateServiceGenerator:
    """Genera en el mismo proceso con el servicio de plantillas existente."""

    def __init__(self, service, institution_id: str):
        self.service = service
        self.institution_id = institution_id

    @staticmethod
    def _fields(certificate: Certificate) -> dict[str, str]:
        source = certificate.generation
        assert source is not None
        return {
            "nombre": source.name,
            "identificacion": source.identification,
            "tipo_asistencia": certificate.role,
            "nombre_taller": certificate.title,
        }

    def supports(self, certificate: Certificate) -> bool:
        source = certificate.generation
        if source is None:
            return False
        try:
            config = self.service.template_repository.get_template_config(
                self.institution_id, source.template_id
            )
        except (FileNotFoundError, KeyError):
            return False
        except Exception as error:
            logger.warning("No se pudo consultar la plantilla (%s)", type(error).__name__)
            raise AppError(ErrorKind.UNAVAILABLE, "El generador no está disponible.") from None
        fields = self._fields(certificate)
        return all(fields.get(key, "").strip() for key in config.get("required_fields", []))

    def generate(self, certificate: Certificate) -> bytes:
        source = certificate.generation
        assert source is not None
        try:
            data = self.service.generate_pdf(
                institution_id=self.institution_id,
                template_id=source.template_id,
                request_data=self._fields(certificate),
            )
        except Exception as error:
            logger.warning("Falló el generador de certificados (%s)", type(error).__name__)
            raise AppError(
                ErrorKind.UNAVAILABLE, "No fue posible generar el certificado."
            ) from None
        if isinstance(data, bytes) and data.startswith(b"%PDF-") and len(data) <= MAX_PDF_BYTES:
            return data
        raise AppError(ErrorKind.UNAVAILABLE, "El generador no devolvió un PDF válido.")
