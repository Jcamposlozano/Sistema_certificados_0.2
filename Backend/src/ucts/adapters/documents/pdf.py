from io import BytesIO
from textwrap import wrap

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen.canvas import Canvas

from ucts.domain.models import Event, Participant


class PdfCertificateRenderer:
    def __init__(self, local: bool = False):
        self.local = local

    def render(self, participant: Participant, event: Event) -> bytes:
        output = BytesIO()
        width, height = landscape(A4)
        canvas = Canvas(output, pagesize=(width, height))
        canvas.setTitle(f"Certificado UCTS - {event.title}")
        canvas.setAuthor("UCTS")
        canvas.setStrokeColor(HexColor("#284f39"))
        canvas.rect(24, 24, width - 48, height - 48)
        canvas.setFillColor(HexColor("#284f39"))
        canvas.setFont("Helvetica-Bold", 20)
        canvas.drawCentredString(width / 2, height - 80, "UCTS / ZONE")
        canvas.setFont("Helvetica", 30)
        canvas.drawCentredString(width / 2, height - 145, "Certificado de participación")
        canvas.setFont("Helvetica", 14)
        canvas.drawCentredString(width / 2, height - 195, "Se reconoce la participación de")
        canvas.setFont("Helvetica-Bold", 20)
        for index, line in enumerate(wrap(participant.name or participant.email, width=55)):
            canvas.drawCentredString(width / 2, height - 235 - index * 25, line)
        canvas.setFont("Helvetica", 17)
        for index, line in enumerate(wrap(event.title, width=65)):
            canvas.drawCentredString(width / 2, 240 - index * 23, line)
        canvas.setFont("Helvetica", 12)
        canvas.drawCentredString(width / 2, 125, f"{event.date:%d/%m/%Y} · {event.hours} horas")
        canvas.setFont("Helvetica", 9)
        canvas.drawCentredString(width / 2, 70, f"Evento: {event.id}")
        if self.local:
            canvas.setFillColor(HexColor("#9e3023"))
            canvas.drawCentredString(width / 2, 45, "DEMOSTRACIÓN LOCAL · SIN VALIDEZ OFICIAL")
        canvas.showPage()
        canvas.save()
        return output.getvalue()
