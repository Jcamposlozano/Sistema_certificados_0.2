from contextlib import closing

from botocore.exceptions import BotoCoreError, ClientError

from ucts.domain.models import AppError, ErrorKind

MAX_PDF_BYTES = 20 * 1024 * 1024


class S3CertificateStore:
    def __init__(self, client, bucket: str):
        self.client = client
        self.bucket = bucket

    def inspect(self, key: str) -> str | None:
        try:
            metadata = self.client.head_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError):
            raise ValueError("No se pudo verificar el objeto en S3.") from None
        if not 0 < metadata["ContentLength"] <= MAX_PDF_BYTES:
            raise ValueError("El objeto debe pesar entre 1 byte y 20 MiB.")
        version = metadata.get("VersionId")
        return version if version and version != "null" else None

    def download(self, bucket: str, key: str, version: str | None) -> bytes:
        if bucket != self.bucket:
            raise AppError(ErrorKind.UNAVAILABLE, "El archivo no está disponible.")
        params = {"Bucket": bucket, "Key": key}
        if version:
            params["VersionId"] = version
        try:
            response = self.client.get_object(**params)
            with closing(response["Body"]) as body:
                if 0 < response["ContentLength"] <= MAX_PDF_BYTES:
                    data = body.read(MAX_PDF_BYTES + 1)
                    if len(data) == response["ContentLength"] and data.startswith(b"%PDF-"):
                        return data
        except (BotoCoreError, ClientError, OSError):
            pass
        raise AppError(ErrorKind.UNAVAILABLE, "El archivo no está disponible.")
