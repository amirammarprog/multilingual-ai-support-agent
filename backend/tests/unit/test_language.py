import pytest

from app.language import detect_language


@pytest.mark.parametrize(
    ("text", "code", "dialect"),
    [
        ("Where is my order BC-10421?", "en", None),
        ("How long is the warranty on laptops?", "en", None),
        ("Bonjour, où en est ma commande ?", "fr", None),
        ("Est-ce que le casque Tessio est disponible ?", "fr", None),
        ("Quel est le délai de remboursement", "fr", None),
        ("أين طلبي؟", "ar", None),
        ("ما هي مدة الضمان على الحواسيب المحمولة؟", "ar", None),
        ("شنوة الحالة متاع الكوموند متاعي؟", "ar", "tn"),
        ("نحب نعرف قداش سوم السماعات", "ar", "tn"),
        ("chnowa el prix mta3 Tessio ANC 700?", "ar", "tn"),
        ("famma livraison l Sfax? 9adech tekhou?", "ar", "tn"),
        ("3andi mochkla m3a el commande mte3i", "ar", "tn"),
    ],
)
def test_detects_language_and_tunisian_dialect(text, code, dialect):
    detected = detect_language(text)
    assert detected.code == code
    assert detected.dialect == dialect


def test_short_ambiguous_message_keeps_conversation_language():
    assert detect_language("ok", prior="fr").code == "fr"
    assert detect_language("👍", prior="ar-tn").tag == "ar-tn"


def test_arabic_indic_digits_do_not_break_detection():
    assert detect_language("طلبي رقم ١٠٤٢١").code == "ar"


def test_tag_includes_dialect():
    assert detect_language("barcha merci, ya3tik saha").tag == "ar-tn"
