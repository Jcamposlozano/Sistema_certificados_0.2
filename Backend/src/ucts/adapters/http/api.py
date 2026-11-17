from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from ucts.domain.models import AppError, ErrorKind, Participant

router = APIRouter(prefix="/api")
COOKIE = "ucts_session"


class RequestOtp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr = Field(max_length=254)


class VerifyOtp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challengeId: str = Field(min_length=32, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    code: str = Field(min_length=6, max_length=8, pattern=r"^\d{6,8}$")


class OtpResponse(BaseModel):
    challengeId: str
    expiresIn: int
    resendAfter: int
    message: str


class EventResponse(BaseModel):
    id: str
    title: str
    category: str
    date: str | None
    hours: int | None
    available: bool


class CertificateResponse(BaseModel):
    id: str
    eventId: str
    title: str
    category: str
    role: str
    available: bool


class ProfileResponse(BaseModel):
    id: str
    name: str
    email: str


def require_origin(request: Request) -> None:
    # Required even for login: protects against login CSRF as well as logout CSRF.
    if request.headers.get("origin") not in request.app.state.settings.allowed_origins:
        raise AppError(ErrorKind.FORBIDDEN, "Origen no permitido.")


def current_participant(
    request: Request,
    ucts_session: Annotated[str | None, Cookie()] = None,
) -> Participant:
    return request.app.state.auth.current(ucts_session)


Current = Annotated[Participant, Depends(current_participant)]


@router.post(
    "/auth/otp/request", response_model=OtpResponse, dependencies=[Depends(require_origin)]
)
def request_otp(body: RequestOtp, request: Request):
    ip = request.client.host if request.client else "unknown"
    challenge = request.app.state.auth.request(str(body.email), ip)
    settings = request.app.state.settings
    return OtpResponse(
        challengeId=challenge,
        expiresIn=settings.otp_ttl_seconds,
        resendAfter=settings.otp_resend_seconds,
        message="Si tu cuenta permite el acceso, recibirás un código en tu correo.",
    )


@router.post("/auth/otp/verify", status_code=204, dependencies=[Depends(require_origin)])
def verify_otp(body: VerifyOtp, request: Request):
    token = request.app.state.auth.verify(body.challengeId, body.code)
    settings = request.app.state.settings
    response = Response(status_code=204)
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_seconds,
        path="/api",
    )
    return response


@router.post("/auth/logout", status_code=204, dependencies=[Depends(require_origin)])
def logout(request: Request, ucts_session: Annotated[str | None, Cookie()] = None):
    request.app.state.auth.logout(ucts_session)
    response = Response(status_code=204)
    response.delete_cookie(
        COOKIE,
        path="/api",
        secure=request.app.state.settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/me", response_model=ProfileResponse)
def profile(participant: Current):
    return ProfileResponse(id=participant.id, name=participant.name, email=participant.email)


@router.get("/me/events", response_model=list[EventResponse])
def events(request: Request, participant: Current):
    return [
        EventResponse(
            id=event.id,
            title=event.title,
            category=event.category,
            date=event.date.isoformat() if event.date else None,
            hours=event.hours,
            available=event.available and request.app.state.settings.auth_mode == "local",
        )
        for event in request.app.state.certificates.events(participant)
    ]


@router.get(
    "/me/events/{event_id}/certificate", responses={200: {"content": {"application/pdf": {}}}}
)
def certificate(event_id: str, request: Request, participant: Current):
    if len(event_id) > 36:
        raise AppError(ErrorKind.NOT_FOUND, "Evento no encontrado.")
    data = request.app.state.certificates.download(participant, event_id)
    return pdf_response(data)


def pdf_response(data: bytes, filename: str = "certificado-ucts.pdf") -> Response:
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/me/certificates", response_model=list[CertificateResponse])
def certificates(request: Request, participant: Current):
    service = request.app.state.certificates
    return [
        CertificateResponse(
            id=certificate.id,
            eventId=certificate.event_id,
            title=certificate.title,
            category=certificate.category,
            role=certificate.role,
            available=service.certificate_available(certificate),
        )
        for certificate in service.certificates(participant)
    ]


@router.get(
    "/me/certificates/{certificate_id}", responses={200: {"content": {"application/pdf": {}}}}
)
def download_certificate(certificate_id: UUID, request: Request, participant: Current):
    return pdf_response(
        request.app.state.certificates.download_certificate(participant, str(certificate_id)),
        filename=f"certificado-{certificate_id}.pdf",
    )
