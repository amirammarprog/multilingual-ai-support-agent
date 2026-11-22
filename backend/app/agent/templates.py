"""Deterministic replies in English, French, Arabic and Tunisian Arabic.

They are used when a model must not improvise: refusals, "I don't know", identity checks, hand-offs,
and as the fallback when a drafted answer fails validation or no model is reachable. Every value
inserted comes from a tool result or the shop record.
"""

from __future__ import annotations

from typing import Any

T: dict[str, dict[str, str]] = {
    "unknown": {
        "en": "I'm sorry, I don't have reliable information to answer that. Would you like me to connect you "
        "with a member of our team?",
        "fr": "Je suis désolé, je n'ai pas d'information fiable pour répondre à cette question. Voulez-vous que "
        "je vous mette en relation avec un conseiller ?",
        "ar": "عذرًا، لا تتوفر لدي معلومات موثوقة للإجابة عن هذا السؤال. هل تريد أن أحولك إلى أحد أعضاء فريقنا؟",
        "ar-tn": "سامحني، ما عنديش معلومة متأكد منها باش نجاوبك. تحب نحولك لواحد من الفريق متاعنا؟",
    },
    "refuse": {
        "en": "I can't help with that request. I can help you with orders, products, stock, shipping, returns "
        "and warranty.",
        "fr": "Je ne peux pas répondre à cette demande. Je peux vous aider pour vos commandes, les produits, le "
        "stock, la livraison, les retours et la garantie.",
        "ar": "لا يمكنني المساعدة في هذا الطلب. يمكنني مساعدتك في الطلبات والمنتجات والمخزون والتوصيل والإرجاع والضمان.",
        "ar-tn": "ما نجمش نعاونك في الطلب هذا. نجم نعاونك في الكوموندات، المنتوجات، الستوك، التوصيل، الإرجاع والضمان.",
    },
    "no_price_change": {
        "en": "I can't change prices or apply discounts. Prices are set by the shop and are the same for every "
        "customer.",
        "fr": "Je ne peux pas modifier les prix ni appliquer de remise. Les prix sont fixés par la boutique et "
        "sont les mêmes pour tous les clients.",
        "ar": "لا يمكنني تغيير الأسعار أو تطبيق أي تخفيض. الأسعار يحددها المتجر وهي نفسها لجميع الزبائن.",
        "ar-tn": "ما نجمش نبدل الأسوام ولا نعمل ريميز. الأسوام يحددها المتجر وهي نفسها للناس الكل.",
    },
    "greeting": {
        "en": "Hello! I'm the {shop} assistant. I can track an order, check if a product is in stock, or answer "
        "questions about shipping, returns and warranty. How can I help?",
        "fr": "Bonjour ! Je suis l'assistant de {shop}. Je peux suivre une commande, vérifier le stock d'un "
        "produit ou répondre à vos questions sur la livraison, les retours et la garantie. Comment puis-je "
        "vous aider ?",
        "ar": "مرحبًا! أنا المساعد الآلي لمتجر {shop}. يمكنني تتبع طلبك، والتحقق من توفر المنتجات، والإجابة عن "
        "أسئلتك حول التوصيل والإرجاع والضمان. كيف يمكنني مساعدتك؟",
        "ar-tn": "عسلامة! أنا المساعد متاع {shop}. نجم نتبعلك الكوموند، نشوفلك كان المنتوج متوفر، ولا نجاوبك على "
        "التوصيل والإرجاع والضمان. كيفاش نجم نعاونك؟",
    },
    "out_of_scope": {
        "en": "I can only help with questions about {shop}: orders, products, shipping, returns and warranty.",
        "fr": "Je peux uniquement vous aider pour {shop} : commandes, produits, livraison, retours et garantie.",
        "ar": "يمكنني فقط المساعدة في ما يخص متجر {shop}: الطلبات والمنتجات والتوصيل والإرجاع والضمان.",
        "ar-tn": "نجم نعاونك كان في الحاجات اللي تخص {shop}: الكوموندات، المنتوجات، التوصيل، الإرجاع والضمان.",
    },
    "verification_required": {
        "en": "To show order {order}, please give me the e-mail address used for this order, or sign in to your "
        "account.",
        "fr": "Pour afficher la commande {order}, indiquez-moi l'adresse e-mail utilisée pour cette commande, ou "
        "connectez-vous à votre compte.",
        "ar": "لعرض الطلب {order}، يرجى إعطائي البريد الإلكتروني المستعمل في هذا الطلب، أو تسجيل الدخول إلى حسابك.",
        "ar-tn": "باش نوريك الكوموند {order}، عطيني الإيمايل اللي عملت بيه الكوموند، ولا اعمل connexion لحسابك.",
    },
    "verification_failed": {
        "en": "I couldn't verify order {order} with these details. Please check the order number and e-mail, or I "
        "can connect you with our team.",
        "fr": "Je n'ai pas pu vérifier la commande {order} avec ces informations. Vérifiez le numéro de commande et "
        "l'e-mail, ou je peux vous mettre en relation avec un conseiller.",
        "ar": "لم أتمكن من التحقق من الطلب {order} بهذه المعلومات. يرجى التأكد من رقم الطلب والبريد الإلكتروني، أو "
        "يمكنني تحويلك إلى فريقنا.",
        "ar-tn": "ما نجمتش نتأكد من الكوموند {order} بالمعلومات هاذي. ثبت في نومرو الكوموند والإيمايل، ولا نحولك "
        "للفريق متاعنا.",
    },
    "verification_locked": {
        "en": "For your security, I can no longer look up orders in this conversation after several unsuccessful "
        "attempts. A member of our team can help you at {email}.",
        "fr": "Pour votre sécurité, je ne peux plus rechercher de commandes dans cette conversation après plusieurs "
        "tentatives infructueuses. Un conseiller peut vous aider à l'adresse {email}.",
        "ar": "حفاظًا على أمانك، لم يعد بإمكاني البحث عن الطلبات في هذه المحادثة بعد عدة محاولات فاشلة. يمكن لفريقنا "
        "مساعدتك عبر {email}.",
        "ar-tn": "على خاطر سلامتك، ما عادش نجم نلوج على الكوموندات في المحادثة هاذي بعد برشا محاولات غالطة. الفريق "
        "يعاونك على {email}.",
    },
    "order_not_found": {
        "en": "I couldn't find order {order} on your account. Please check the number.",
        "fr": "Je ne trouve pas la commande {order} sur votre compte. Vérifiez le numéro, s'il vous plaît.",
        "ar": "لم أجد الطلب {order} في حسابك. يرجى التحقق من الرقم.",
        "ar-tn": "ما لقيتش الكوموند {order} في الحساب متاعك. ثبت في النومرو.",
    },
    "order_number_missing": {
        "en": "Could you give me your order number? You will find it in your confirmation e-mail (two letters, a dash and digits).",
        "fr": "Pouvez-vous me donner votre numéro de commande ? Il figure dans l'e-mail de confirmation (deux lettres, un tiret et des chiffres).",
        "ar": "هل يمكنك إعطائي رقم الطلب؟ تجده في رسالة التأكيد (حرفان ثم شرطة ثم أرقام).",
        "ar-tn": "تنجم تعطيني نومرو الكوموند؟ تلقاه في الإيمايل متاع التأكيد (زوز حروف، شرطة وأرقام).",
    },
    "order_status": {
        "en": "Order {order} is {status_label}.",
        "fr": "La commande {order} est {status_label}.",
        "ar": "حالة الطلب {order}: {status_label}.",
        "ar-tn": "الكوموند {order}: {status_label}.",
    },
    "order_tracking": {
        "en": " Carrier: {carrier}, tracking number {tracking}.",
        "fr": " Transporteur : {carrier}, numéro de suivi {tracking}.",
        "ar": " شركة التوصيل: {carrier}، رقم التتبع {tracking}.",
        "ar-tn": " شركة التوصيل: {carrier}، نومرو التتبع {tracking}.",
    },
    "order_eta": {
        "en": " Estimated delivery date: {eta}.",
        "fr": " Date de livraison estimée : {eta}.",
        "ar": " تاريخ التسليم المتوقع: {eta}.",
        "ar-tn": " التاريخ المتوقع للتوصيل: {eta}.",
    },
    "order_no_eta": {
        "en": " The carrier has not given an estimated delivery date yet.",
        "fr": " Le transporteur n'a pas encore communiqué de date de livraison estimée.",
        "ar": " لم تقدم شركة التوصيل تاريخًا متوقعًا للتسليم بعد.",
        "ar-tn": " شركة التوصيل مازالت ما عطاتش تاريخ متوقع للتوصيل.",
    },
    "order_delivered_on": {
        "en": " Delivered on {date}.",
        "fr": " Livrée le {date}.",
        "ar": " تم التسليم بتاريخ {date}.",
        "ar-tn": " توصلت نهار {date}.",
    },
    "stock": {
        "en": "{name} ({sku}) is {label}.",
        "fr": "{name} ({sku}) est {label}.",
        "ar": "{name} ({sku}): {label}.",
        "ar-tn": "{name} ({sku}): {label}.",
    },
    "stock_low": {
        "en": " Only {qty} left.",
        "fr": " Il n'en reste que {qty}.",
        "ar": " بقي {qty} فقط.",
        "ar-tn": " مازال {qty} برك.",
    },
    "restock_date": {
        "en": " Expected back in stock on {date}.",
        "fr": " Retour en stock prévu le {date}.",
        "ar": " من المتوقع أن يعود إلى المخزون بتاريخ {date}.",
        "ar-tn": " متوقع يرجع للستوك نهار {date}.",
    },
    "restock_unknown": {
        "en": " We don't have a confirmed restock date.",
        "fr": " Nous n'avons pas de date de retour en stock confirmée.",
        "ar": " لا يوجد لدينا تاريخ مؤكد لعودته إلى المخزون.",
        "ar-tn": " ما عناش تاريخ مؤكد باش يرجع للستوك.",
    },
    "product": {
        "en": "{name} ({sku}) costs {price} {currency}, with a {warranty}-month warranty. It is {label}.",
        "fr": "{name} ({sku}) coûte {price} {currency}, avec une garantie de {warranty} mois. Il est {label}.",
        "ar": "{name} ({sku}) سعره {price} {currency}، مع ضمان لمدة {warranty} شهرًا. الحالة: {label}.",
        "ar-tn": "{name} ({sku}) سومو {price} {currency}، بضمان {warranty} شهر. الحالة: {label}.",
    },
    "product_not_identified": {
        "en": "Which product do you mean? You can give me its name or SKU.",
        "fr": "De quel produit parlez-vous ? Vous pouvez me donner son nom ou sa référence.",
        "ar": "ما هو المنتج الذي تقصده؟ يمكنك إعطائي اسمه أو رمزه.",
        "ar-tn": "شنوة المنتوج اللي تحكي عليه؟ عطيني الإسم متاعو ولا الرمز.",
    },
    "search_results": {
        "en": "Here is what I found in our catalogue:",
        "fr": "Voici ce que j'ai trouvé dans notre catalogue :",
        "ar": "هذا ما وجدته في كتالوجنا:",
        "ar-tn": "هاذا اللي لقيتو في الكاتالوغ متاعنا:",
    },
    "search_empty": {
        "en": "I couldn't find a matching product in our catalogue.",
        "fr": "Je n'ai pas trouvé de produit correspondant dans notre catalogue.",
        "ar": "لم أجد منتجًا مطابقًا في كتالوجنا.",
        "ar-tn": "ما لقيتش منتوج يتطابق في الكاتالوغ متاعنا.",
    },
    "ticket_created": {
        "en": "I've opened ticket {ticket}. Our team will reply by e-mail within {hours} hours.",
        "fr": "J'ai ouvert le ticket {ticket}. Notre équipe vous répondra par e-mail sous {hours} heures.",
        "ar": "قمت بفتح التذكرة {ticket}. سيرد عليك فريقنا عبر البريد الإلكتروني خلال {hours} ساعات.",
        "ar-tn": "حليتلك تيكيت {ticket}. الفريق باش يجاوبك بالإيمايل في ظرف {hours} سوايع.",
    },
    "contact_email_required": {
        "en": "To open a ticket, I need an e-mail address where our team can reply to you.",
        "fr": "Pour ouvrir un ticket, j'ai besoin d'une adresse e-mail à laquelle notre équipe pourra vous répondre.",
        "ar": "لفتح تذكرة، أحتاج إلى بريد إلكتروني يمكن لفريقنا الرد عليك من خلاله.",
        "ar-tn": "باش نحل تيكيت، نستحق إيمايل باش الفريق يجاوبك عليه.",
    },
    "ticket_limit_reached": {
        "en": "Several tickets are already open for this conversation; our team will contact you.",
        "fr": "Plusieurs tickets sont déjà ouverts pour cette conversation ; notre équipe va vous contacter.",
        "ar": "توجد عدة تذاكر مفتوحة لهذه المحادثة بالفعل، وسيتواصل معك فريقنا.",
        "ar-tn": "فما برشا تيكيات محلولة للمحادثة هاذي، الفريق باش يكلمك.",
    },
    "handoff": {
        "en": "I've passed your conversation to our support team (reference {ticket}). A team member will reply "
        "within {hours} hours. Our team is available {support_hours}.",
        "fr": "J'ai transmis votre conversation à notre équipe (référence {ticket}). Un conseiller vous répondra "
        "sous {hours} heures. Notre équipe est disponible {support_hours}.",
        "ar": "قمت بتحويل محادثتك إلى فريق الدعم (المرجع {ticket}). سيرد عليك أحد أعضاء الفريق خلال {hours} ساعات. "
        "أوقات عمل الفريق: {support_hours}.",
        "ar-tn": "حولت المحادثة متاعك للفريق (المرجع {ticket}). واحد من الفريق باش يجاوبك في ظرف {hours} سوايع. "
        "الفريق يخدم {support_hours}.",
    },
    "degraded": {
        "en": "Our assistant is temporarily limited. ",
        "fr": "Notre assistant fonctionne en mode limité. ",
        "ar": "يعمل مساعدنا حاليًا بشكل محدود. ",
        "ar-tn": "المساعد متاعنا يخدم توا بطريقة محدودة. ",
    },
    "degraded_offer": {
        "en": "If this does not answer your question, I can connect you with a member of our team.",
        "fr": "Si cela ne répond pas à votre question, je peux vous mettre en relation avec un conseiller.",
        "ar": "إذا لم يجب هذا عن سؤالك، يمكنني تحويلك إلى أحد أعضاء فريقنا.",
        "ar-tn": "كان هذا ما جاوبكش، نجم نحولك لواحد من الفريق متاعنا.",
    },
    "source_hint": {
        "en": 'The most relevant section of our documents is "{title}":',
        "fr": "La section la plus pertinente de nos documents est « {title} » :",
        "ar": 'القسم الأكثر صلة في وثائقنا هو "{title}":',
        "ar-tn": 'الجزء اللي يخص سؤالك في الوثائق متاعنا هو "{title}":',
    },
}


_MONTHS = {
    "en": [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ],
    "fr": [
        "janvier",
        "février",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "août",
        "septembre",
        "octobre",
        "novembre",
        "décembre",
    ],
    "ar": ["جانفي", "فيفري", "مارس", "أفريل", "ماي", "جوان", "جويلية", "أوت", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"],
}


def format_date(iso: str, language: str) -> str:
    """2026-11-24 -> "24 November 2026" / "24 novembre 2026" / "24 نوفمبر 2026" (Maghreb month names)."""
    try:
        year, month, day = (int(x) for x in iso[:10].split("-"))
    except ValueError:
        return iso
    months = _MONTHS.get(language.split("-")[0], _MONTHS["en"])
    return f"{day} {months[month - 1]} {year}"


def lang_key(language: str, dialect: str | None) -> str:
    return "ar-tn" if language == "ar" and dialect == "tn" else (language if language in ("en", "fr", "ar") else "en")


def render(key: str, language: str, dialect: str | None = None, **values: Any) -> str:
    variants = T[key]
    template = variants.get(lang_key(language, dialect)) or variants["en"]
    return template.format(**values)
