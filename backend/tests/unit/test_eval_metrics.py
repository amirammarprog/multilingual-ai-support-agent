"""Number checks of the evaluation: numbers written as words count as the number."""

import pytest

from evals.metrics import spelled_numbers


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Delivery takes two to four business days.", {"2", "4"}),
        ("Returns are accepted within fifteen days.", {"15"}),
        ("La livraison prend entre un et deux jours ouvrables.", {"1", "2"}),
        ("Comptez un à deux jours.", {"1", "2"}),
        ("Remboursement sous quinze jours, réponse en vingt-quatre heures.", {"15", "24"}),
        ("مدة التوصيل إلى تونس العاصمة هي من يوم إلى يومين عمل.", {"1", "2"}),
        ("التوصيل يستغرق من يومين إلى أربعة أيام عمل", {"2", "4"}),
        ("التوصيل ياخذ زوز ولا ثلاثة أيام", {"2", "3"}),
        ("الإرجاع ممكن خلال خمسة عشر يوما", {"15"}),
        ("الضمان اثنا عشر شهرا", {"12"}),
        ("ويومين للتوصيل", {"2"}),
    ],
)
def test_numbers_written_as_words(text, expected):
    assert spelled_numbers(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Un conseiller vous répondra.",  # article, not a number
        "Une erreur est survenue, un remboursement est possible.",
        "One of our team will contact you.",
        "اليوم إلى المساء",  # "today", not "one day"
        "No numbers here at all.",
    ],
)
def test_words_that_are_not_numbers(text):
    assert spelled_numbers(text) == set()
