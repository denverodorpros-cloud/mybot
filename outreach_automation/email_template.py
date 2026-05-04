from __future__ import annotations

from html import escape

from .config import Settings
from .models import EmailMessage


SUBJECT = "Odor removal help for your listing"


def render_email(
    *,
    agent_name: str,
    property_address: str,
    settings: Settings,
) -> EmailMessage:
    plain_signature = f"""Best regards,
Denver Odor Pros LLC
Phone: {settings.business_phone}
Website: {settings.business_website}
Email: {settings.business_email}
Mailing address: {settings.business_address}
_________________________________________"""

    body = f"""Hi {agent_name},

This is {settings.contact_name} with {settings.business_name}. I saw your active listing at {property_address} and wanted to reach out in case odor removal is needed before showings, inspection, or closing.

We help real estate agents and sellers eliminate smoke, pet, urine, kitchen, and musty odors so homes smell fresh and show better.

Our ozone odor removal treatment includes a 100% odor-removal guarantee, and a fresh-smelling home can make a stronger first impression with buyers and help the property show better.

We offer fast scheduling in the Denver area and surrounding cities.

{plain_signature}

Reply STOP and we won’t contact you again."""

    html_body = f"""<!doctype html>
<html>
  <body style="font-family: Arial, sans-serif; color: #1f2937; font-size: 15px; line-height: 1.5;">
    <p>Hi {escape(agent_name)},</p>
    <p>This is {escape(settings.contact_name)} with {escape(settings.business_name)}. I saw your active listing at {escape(property_address)} and wanted to reach out in case odor removal is needed before showings, inspection, or closing.</p>
    <p>We help real estate agents and sellers eliminate smoke, pet, urine, kitchen, and musty odors so homes smell fresh and show better.</p>
    <p>Our ozone odor removal treatment includes a 100% odor-removal guarantee, and a fresh-smelling home can make a stronger first impression with buyers and help the property show better.</p>
    <p>We offer fast scheduling in the Denver area and surrounding cities.</p>
    <p>
      Best regards,<br>
      <strong>Denver Odor Pros LLC</strong><br>
      Phone: {escape(settings.business_phone)}<br>
      Website: <a href="https://{escape(settings.business_website.removeprefix('https://').removeprefix('http://'))}">{escape(settings.business_website)}</a><br>
      Email: <a href="mailto:{escape(settings.business_email)}">{escape(settings.business_email)}</a><br>
      Mailing address: {escape(settings.business_address)}
    </p>
    <p><img src="cid:denver-odor-pros-logo" alt="Denver Odor Pros LLC logo" style="max-width: 520px; width: 100%; height: auto;"></p>
    <p style="border-top: 1px solid #d1d5db; padding-top: 12px;">Reply STOP and we won’t contact you again.</p>
  </body>
</html>"""

    return EmailMessage(subject=SUBJECT, body=body, html_body=html_body)
