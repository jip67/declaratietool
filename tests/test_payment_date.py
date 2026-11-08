"""De secretaris kiest de datum van de betaling; de indiener ziet 'ingepland op' of 'betaald op'."""

from datetime import timedelta

from sqlalchemy import select

from app import intake, workflow
from app.models import Claim, Status

from .conftest import SIGNATURE, jpeg_bytes, login
from .test_workflow import IBAN, make_mail, sent_to


def _prepared_claim(db, client):
    intake.process_message(db, make_mail([("bon.jpg", "image/jpeg", jpeg_bytes())]))
    claim = db.scalar(select(Claim))
    client.post(f"/c/{claim.token}", data={"iban": IBAN, "account_holder": "P. Jansen",
                                          "description": "Boodschappen", "amount": "12,50"})
    for email, action in (("voorzitter@example.org", "approve"), ("boekhouder@example.org", "prepare")):
        login(client, email)
        client.post(f"/portal/claims/{claim.id}/action", data={"action": action, "signature": SIGNATURE})
    db.expire_all()
    assert claim.status == Status.PAYMENT_PREPARED.value
    login(client, "secretaris@example.org")
    return claim


def _pay(client, claim, payment_date):
    return client.post(f"/portal/claims/{claim.id}/action", data={"action": "pay", "payment_date": payment_date},
                       follow_redirects=False)


def test_form_defaults_to_today(db, client, staff):
    claim = _prepared_claim(db, client)
    page = client.get(f"/portal/claims/{claim.id}").text
    assert f'name="payment_date" value="{workflow.local_today().isoformat()}"' in page


def test_scheduled_payment_is_shown_to_submitter(db, client, staff):
    claim = _prepared_claim(db, client)
    when = workflow.local_today() + timedelta(days=2)
    _pay(client, claim, when.isoformat())
    db.expire_all()
    assert claim.status == Status.PAID.value
    assert claim.payment_date == when
    text = f"De betaling is ingepland op {workflow.long_date(when, 'nl')}"
    mail = sent_to("piet@example.org")[-1]
    assert "Betaling ingepland" in mail["Subject"]
    assert text in mail.get_content()
    assert text in client.get(f"/c/{claim.token}").text
    portal = client.get(f"/portal/claims/{claim.id}").text
    assert text in portal and "betaaldatum" in portal


def test_today_or_past_shows_paid_on(db, client, staff):
    claim = _prepared_claim(db, client)
    when = workflow.local_today() - timedelta(days=1)
    _pay(client, claim, when.isoformat())
    db.expire_all()
    mail = sent_to("piet@example.org")[-1]
    assert "Betaald" in mail["Subject"]
    assert f"Betaald op {workflow.long_date(when, 'nl')}" in mail.get_content()


def test_scheduled_becomes_paid_when_date_passes(db, client, staff, monkeypatch):
    claim = _prepared_claim(db, client)
    when = workflow.local_today() + timedelta(days=2)
    _pay(client, claim, when.isoformat())
    db.expire_all()
    monkeypatch.setattr(workflow, "local_today", lambda: when)
    assert workflow.payment_note(claim, "nl") == f"Betaald op {workflow.long_date(when, 'nl')}."


def test_invalid_or_out_of_range_dates_are_refused(db, client, staff):
    claim = _prepared_claim(db, client)
    for value, error in (("morgen", "payment_date_invalid"),
                         ((workflow.local_today() + timedelta(days=400)).isoformat(), "payment_date_range"),
                         ((workflow.local_today() - timedelta(days=100)).isoformat(), "payment_date_range")):
        r = _pay(client, claim, value)
        assert f"error={error}" in r.headers["location"]
        db.expire_all()
        assert claim.status == Status.PAYMENT_PREPARED.value


def test_undo_clears_payment_date(db, client, staff):
    claim = _prepared_claim(db, client)
    _pay(client, claim, workflow.local_today().isoformat())
    client.post(f"/portal/claims/{claim.id}/action", data={"action": "undo"})
    db.expire_all()
    assert claim.status == Status.PAYMENT_PREPARED.value and claim.payment_date is None


def test_old_paid_claims_fall_back_to_click_date(db, client, staff):
    claim = _prepared_claim(db, client)
    _pay(client, claim, "")
    db.expire_all()
    claim.payment_date = None
    db.commit()
    assert workflow.payment_note(claim, "en") == f"Paid on {workflow.long_date(workflow.local_today(), 'en')}."


def test_long_date():
    from datetime import date
    assert workflow.long_date(date(2026, 11, 10), "nl") == "10 november 2026"
    assert workflow.long_date(date(2026, 11, 10), "en") == "November 10, 2026"
