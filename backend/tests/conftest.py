import pytest

from app.services.crm.config import DEFAULT_AUTOMATION


@pytest.fixture(autouse=True)
def fixed_crm_hours(monkeypatch):
    """The CRM tests are written for fixed hours (Mon–Sat 09:00–18:00 IST)
    and no night queue, independent of the configurable defaults. Lead
    intake reads the real clock, so a night queue left on would make the
    result depend on when the suite runs; tests of the queue turn it on."""
    monkeypatch.setitem(DEFAULT_AUTOMATION, "working_hours",
                        {"start": "09:00", "end": "18:00", "days": [0, 1, 2, 3, 4, 5]})
    monkeypatch.setitem(DEFAULT_AUTOMATION, "night_queue", False)


@pytest.fixture(autouse=True)
def no_background_whatsapp(monkeypatch):
    """Automatic WhatsApp sends run in their own session against the real
    database; tests call services.whatsapp.auto._run directly instead."""
    from app.services.whatsapp import auto
    monkeypatch.setattr(auto, "ENABLED", False)
