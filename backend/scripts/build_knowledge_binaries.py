"""Generate the PDF and DOCX documents of the fictional knowledge base.

The text lives here so the binary files can be rebuilt and reviewed in a diff:

    python scripts/build_knowledge_binaries.py
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from fpdf import FPDF

OUT = Path(__file__).resolve().parents[1] / "knowledge" / "demo-shop"

WARRANTY = [
    ("h1", "Brightcart Electronics - Warranty Policy"),
    ("p", "Brightcart Electronics is a fictional online shop used for demonstrations."),
    ("h2", "1. Warranty periods"),
    ("p", "The warranty starts on the delivery date shown on your invoice."),
    ("li", "Smartphones, laptops and tablets: 24 months."),
    ("li", "Audio products (headphones, earbuds, speakers): 12 months."),
    ("li", "Wearables (smartwatches, fitness bands): 12 months."),
    ("li", "Smart-home products (cameras): 12 months."),
    ("li", "Accessories (chargers, mice, keyboards, styluses): 12 months."),
    ("li", "Built-in batteries are covered for 12 months, including on products with a 24-month warranty."),
    ("h2", "2. What the warranty covers"),
    (
        "p",
        "The warranty covers manufacturing defects and failures that happen during normal use: a "
        "device that does not turn on, a screen with dead pixels at delivery, a charging port that "
        "stops working, a battery that swells.",
    ),
    ("h2", "3. What the warranty does not cover"),
    ("li", "Accidental damage such as drops, cracked or broken screens and bent frames."),
    ("li", "Liquid damage, including on products with a water-resistance rating."),
    ("li", "Repairs or opening of the device by anyone other than our partner service centre."),
    ("li", "Normal wear and cosmetic scratches."),
    ("li", "Loss or theft."),
    ("h2", "4. How to make a warranty claim"),
    (
        "p",
        "Open a support ticket with your order number, a description of the problem and photos or "
        "a short video. Our team replies within 1 business day.",
    ),
    (
        "p",
        "We collect the product for free. Our partner service centre diagnoses it within 5 business "
        "days. Repairs are completed within 15 business days after the diagnosis. If the product "
        "cannot be repaired, we replace it with the same model or, if it is no longer sold, refund "
        "the purchase price.",
    ),
    ("p", "Collection and return shipping are free during the warranty period."),
    ("h2", "5. Extended warranty"),
    ("p", "Brightcart Electronics does not sell extended warranties or insurance plans."),
]

FAQ_FR = [
    ("h1", "Brightcart Electronics : questions fréquentes"),
    ("p", "Brightcart Electronics est une boutique en ligne fictive utilisée pour des démonstrations."),
    ("h2", "Comment créer un compte ou réinitialiser mon mot de passe ?"),
    (
        "p",
        "Cliquez sur « Mon compte » puis « Mot de passe oublié ». Un lien valable 30 minutes est "
        "envoyé à votre adresse e-mail. L'assistant du support ne peut pas changer votre mot de passe.",
    ),
    ("h2", "Puis-je utiliser plusieurs codes promo ?"),
    (
        "p",
        "Non. Un seul code promo est accepté par commande, il n'est pas cumulable avec les autres "
        "offres et il doit être saisi avant la validation de la commande. Un code ne peut pas être "
        "ajouté à une commande déjà validée.",
    ),
    ("h2", "Pratiquez-vous l'alignement des prix ?"),
    (
        "p",
        "Non, nous ne remboursons pas la différence si un produit est moins cher ailleurs ou si son "
        "prix baisse après votre achat.",
    ),
    ("h2", "Vendez-vous des cartes cadeaux ?"),
    ("p", "Pas pour le moment."),
    ("h2", "Puis-je obtenir une facture professionnelle ?"),
    (
        "p",
        "Oui. Indiquez le nom de votre société et votre matricule fiscal au moment de la commande. "
        "La facture ne peut plus être modifiée après l'expédition.",
    ),
    ("h2", "Puis-je retirer ma commande en magasin ?"),
    ("p", "Non, nous n'avons pas de magasin physique. Toutes les commandes sont livrées."),
    ("h2", "Prenez-vous des précommandes ?"),
    (
        "p",
        "Non. Quand un produit est en rupture de stock, vous pouvez demander au support d'être "
        "prévenu par e-mail lorsqu'il revient en stock.",
    ),
    ("h2", "Les stocks affichés sont-ils fiables ?"),
    ("p", "Oui, les stocks sont mis à jour en temps réel. L'assistant consulte le stock en direct."),
    ("h2", "Comment contacter un conseiller ?"),
    (
        "p",
        "L'assistant répond 24h/24. Les conseillers répondent du lundi au samedi, de 9h00 à 18h00 "
        "(heure de Tunis), sous 4 heures ouvrées pour les demandes transférées par l'assistant.",
    ),
]


def build_pdf() -> None:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    for kind, text in WARRANTY:
        if kind == "h1":
            pdf.set_font("Helvetica", "B", 16)
            pdf.multi_cell(0, 9, text, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        elif kind == "h2":
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 12)
            pdf.multi_cell(0, 7, text, new_x="LMARGIN", new_y="NEXT")
        elif kind == "li":
            pdf.set_font("Helvetica", "", 11)
            pdf.multi_cell(0, 6, "- " + text, new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_font("Helvetica", "", 11)
            pdf.multi_cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
    pdf.output(str(OUT / "warranty-policy.pdf"))


def build_docx() -> None:
    doc = Document()
    for kind, text in FAQ_FR:
        if kind == "h1":
            doc.add_heading(text, level=1)
        elif kind == "h2":
            doc.add_heading(text, level=2)
        else:
            doc.add_paragraph(text)
    doc.core_properties.title = "FAQ Brightcart Electronics"
    doc.save(str(OUT / "faq-fr.docx"))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    build_pdf()
    build_docx()
    print("wrote", OUT / "warranty-policy.pdf", "and", OUT / "faq-fr.docx")
