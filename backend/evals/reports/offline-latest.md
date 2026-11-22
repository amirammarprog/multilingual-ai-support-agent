# Evaluation report: offline mode

- Date: 2026-11-22T18:22:01.389270+00:00 · trigger: local · git: `n/a`
- Dataset: 130 cases, version `60b56bfad050`
- Passed: **91/130 (70.0%)**
- Planner/answers: offline: rule-based planner and deterministic templates, no LLM
- Latency: avg 553 ms, p95 779 ms · model cost: $0.0000

## Metrics

| Metric | Score | Change vs previous run |
| --- | ---: | ---: |
| Pass rate (all checks of a case pass) | 70.0% | +0.0 pt |
| Correctness (expected outcome and facts) | 73.1% | +0.0 pt |
| Retrieval hit rate (expected document retrieved) | 75.9% | +0.0 pt |
| Retrieval MRR | 71.8% | +0.0 pt |
| Faithfulness (no number outside the evidence) | 100.0% | +0.0 pt |
| Hallucination rate (lower is better) | 0.8% | +0.0 pt |
| Language consistency | 96.2% | +0.0 pt |
| Tool selection accuracy | 97.4% | +0.0 pt |
| Tool execution accuracy | 96.9% | +0.0 pt |
| Injection / abuse resistance | 100.0% | +0.0 pt |

## By language

| Language | Cases | Pass rate | Correctness | Language consistency | Hallucination |
| --- | ---: | ---: | ---: | ---: | ---: |
| ar | 20 | 75.0% | 80.0% | 95.0% | 0.0% |
| ar-tn | 15 | 60.0% | 60.0% | 100.0% | 0.0% |
| en | 62 | 71.0% | 72.6% | 96.8% | 1.6% |
| fr | 33 | 69.7% | 75.8% | 93.9% | 0.0% |

## By category

| Category | Cases | Pass rate |
| --- | ---: | ---: |
| cross_customer | 5 | 100.0% |
| followup | 4 | 100.0% |
| greeting | 4 | 100.0% |
| handoff | 4 | 100.0% |
| injection | 7 | 100.0% |
| order_status | 13 | 100.0% |
| policy | 54 | 38.9% |
| price_manipulation | 4 | 100.0% |
| product_info | 12 | 83.3% |
| product_search | 5 | 100.0% |
| stock | 8 | 75.0% |
| ticket | 3 | 100.0% |
| unknown | 7 | 71.4% |

## Failed cases (39)

| Case | Question | Answer (start) | Reasons |
| --- | --- | --- | --- |
| `ship-en-01` | How much does standard delivery cost? | I couldn't find a matching product in our catalogue. | missing number 7 |
| `ship-en-02` | Is delivery free if I spend 350 dinars? | I'm sorry, I don't have reliable information to answer that. Would you like me to connect you with a member of our team? | outcome unknown not in ['answered']; missing number 300 |
| `ship-en-03` | Can I get express delivery in Sfax? | Our assistant is temporarily limited. The most relevant section of our documents is "الأسئلة الشائعة - برايتكارت للإلكترونيات": «نعم، تُرسل الفاتورة إلى بريدك ا | missing one of ['Grand Tunis', 'only', 'not available']; expected document 'Shipping' not retrieved |
| `ship-fr-01` | Combien de temps prend la livraison à Bizerte ? | Je n'ai pas trouvé de produit correspondant dans notre catalogue. | missing number 2; missing number 4 |
| `ship-fr-02` | Quels transporteurs utilisez-vous ? | Je suis désolé, je n'ai pas d'information fiable pour répondre à cette question. Voulez-vous que je vous mette en relation avec un conseiller ? | outcome unknown not in ['answered']; missing one of ['SwiftDrop']; missing one of ['Medina Courier']; expected document 'Shipping' not retrieved |
| `ship-ar-01` | كم مدة التوصيل إلى تونس العاصمة؟ | يعمل مساعدنا حاليًا بشكل محدود. القسم الأكثر صلة في وثائقنا هو "الأسئلة الشائعة - برايتكارت للإلكترونيات": «من يوم إلى يومي عمل في تونس الكبرى، ومن يومين إلى أر | missing number 1; missing number 2 |
| `ship-ar-02` | هل التوصيل مجاني؟ | عذرًا، لا تتوفر لدي معلومات موثوقة للإجابة عن هذا السؤال. هل تريد أن أحولك إلى أحد أعضاء فريقنا؟ | outcome unknown not in ['answered']; missing number 300 |
| `ship-tn-01` | قداش يخلص التوصيل العادي؟ | شنوة المنتوج اللي تحكي عليه؟ عطيني الإسم متاعو ولا الرمز. | outcome needs_info not in ['answered']; missing number 7 |
| `ship-tn-02` | famma livraison express l Sousse? | شنوة المنتوج اللي تحكي عليه؟ عطيني الإسم متاعو ولا الرمز. | outcome needs_info not in ['answered']; missing one of ['تونس الكبرى', 'Grand Tunis'] |
| `ret-en-02` | Can I return headphones I already opened? | I'm sorry, I don't have reliable information to answer that. Would you like me to connect you with a member of our team? | outcome unknown not in ['answered']; missing one of ['defect', 'défaut', 'hygiene', 'not']; expected document 'retours' not retrieved |
| `ret-en-03` | Who pays the return shipping if I just changed my mind? | I'm sorry, I don't have reliable information to answer that. Would you like me to connect you with a member of our team? | outcome unknown not in ['answered']; missing number 7; expected document 'retours' not retrieved |
| `ret-en-04` | How long does a refund take? | Our assistant is temporarily limited. The most relevant section of our documents is "الأسئلة الشائعة - برايتكارت للإلكترونيات": «يمكنك إرجاع المنتج خلال 15 يومً | missing number 7; expected document 'retours' not retrieved |
| `ret-fr-01` | Quel est le délai de retour ? | Notre assistant fonctionne en mode limité. La section la plus pertinente de nos documents est « الأسئلة الشائعة - برايتكارت للإلكترونيات » : «يمكنك إرجاع المنتج | expected document 'retours' not retrieved |
| `ret-fr-03` | Les frais de livraison sont-ils remboursés en cas de retour ? | Je n'ai pas trouvé de produit correspondant dans notre catalogue. | missing one of ['défectueux', 'erreur'] |
| `ret-fr-04` | Mon colis est arrivé abîmé, que faire ? | Je suis désolé, je n'ai pas d'information fiable pour répondre à cette question. Voulez-vous que je vous mette en relation avec un conseiller ? | outcome unknown not in ['answered', 'ticket_created']; missing number 48 |
| `ret-ar-02` | هل يمكنني استبدال المنتج بموديل آخر؟ | يعمل مساعدنا حاليًا بشكل محدود. القسم الأكثر صلة في وثائقنا هو "⁨Brightcart Electronics : politique de retours et de remboursements⁩": «Un échange contre un aut | answered in fr, expected ar |
| `ret-tn-01` | نجم نرجع سماعات حليتهم؟ | سامحني، ما عنديش معلومة متأكد منها باش نجاوبك. تحب نحولك لواحد من الفريق متاعنا؟ | outcome unknown not in ['answered']; missing one of ['عيب', 'صحية', 'défaut', 'لا'] |
| `ret-tn-02` | 9adech 3andi wa9t bech nraja3 produit? | شنوة المنتوج اللي تحكي عليه؟ عطيني الإسم متاعو ولا الرمز. | outcome needs_info not in ['answered']; missing number 15 |
| `war-en-02` | Is a cracked screen covered by the warranty? | Our assistant is temporarily limited. The most relevant section of our documents is "Warranty Policy": «- Accidental damage such as drops, cracked or broken scr | missing one of ['not covered', 'does not cover', 'not', 'excluded'] |
| `war-en-05` | My watch got water inside, is that covered? It is water resistant. | I'm sorry, I don't have reliable information to answer that. Would you like me to connect you with a member of our team? | outcome unknown not in ['answered']; missing one of ['not', 'liquid']; expected document 'Warranty' not retrieved |
| `war-fr-01` | Quelle est la garantie des écouteurs ? | Je suis désolé, je n'ai pas d'information fiable pour répondre à cette question. Voulez-vous que je vous mette en relation avec un conseiller ? | outcome unknown not in ['answered']; missing number 12 |
| `war-fr-02` | La garantie commence à quelle date ? | Notre assistant fonctionne en mode limité. La section la plus pertinente de nos documents est « Warranty Policy » : «The warranty starts on the delivery date sh | missing one of ['livraison']; answered in en, expected fr |
| `war-ar-02` | هل الضمان يشمل الأضرار الناتجة عن السوائل؟ | عذرًا، لا تتوفر لدي معلومات موثوقة للإجابة عن هذا السؤال. هل تريد أن أحولك إلى أحد أعضاء فريقنا؟ | outcome unknown not in ['answered'] |
| `faq-en-01` | Which payment methods do you accept? | Our assistant is temporarily limited. The most relevant section of our documents is "الأسئلة الشائعة - برايتكارت للإلكترونيات": «- الدفع عند الاستلام للطلبات ال | missing one of ['cash on delivery', 'delivery']; missing one of ['card']; missing one of ['transfer'] |
| `faq-en-02` | Can I pay in installments? | I'm sorry, I don't have reliable information to answer that. Would you like me to connect you with a member of our team? | outcome unknown not in ['answered']; missing one of ['not', 'no'] |
| `faq-en-03` | Can I cancel my order after placing it? | Our assistant is temporarily limited. The most relevant section of our documents is "الأسئلة الشائعة - برايتكارت للإلكترونيات": «نعم، يمكنك تعديل الطلب أو إلغاؤ | missing number 2 |
| `faq-en-04` | Do you have a physical store I can visit? | I'm sorry, I don't have reliable information to answer that. Would you like me to connect you with a member of our team? | outcome unknown not in ['answered']; missing one of ['online', 'no', 'not'] |
| `faq-en-05` | Can I use two promo codes on one order? | Our assistant is temporarily limited. The most relevant section of our documents is "Brightcart Electronics : questions fréquentes": «Non. Un seul code promo es | missing one of ['one', 'single', 'only']; answered in fr, expected en |
| `faq-en-06` | Do you match prices from other shops? | Our assistant is temporarily limited. The most relevant section of our documents is "Brightcart Electronics : questions fréquentes": «Non, nous ne remboursons p | answered in fr, expected en |
| `faq-en-07` | Do you sell gift cards? | Our assistant is temporarily limited. The most relevant section of our documents is "الأسئلة الشائعة - برايتكارت للإلكترونيات": «نعم، تُرسل الفاتورة إلى بريدك ا | missing one of ['not', 'no'] |
| `faq-fr-01` | Puis-je avoir une facture au nom de ma société ? | Je n'ai pas trouvé de produit correspondant dans notre catalogue. | missing one of ['matricule', 'société'] |
| `faq-ar-01` | هل يمكنني الدفع بالتقسيط؟ | عذرًا، لا تتوفر لدي معلومات موثوقة للإجابة عن هذا السؤال. هل تريد أن أحولك إلى أحد أعضاء فريقنا؟ | outcome unknown not in ['answered'] |
| `faq-tn-01` | شنوة طرق الخلاص اللي عندكم؟ | سامحني، ما عنديش معلومة متأكد منها باش نجاوبك. تحب نحولك لواحد من الفريق متاعنا؟ | outcome unknown not in ['answered']; missing one of ['الاستلام', 'livraison']; missing one of ['البطاقة', 'بطاقة', 'carte'] |
| `prod-en-02` | What is the battery life of the Tessio ANC 700? | Tessio ANC 700 wireless headphones (TES-ANC-700) costs 389.000 TND, with a 12-month warranty. It is in stock. | missing number 30 |
| `prod-fr-03` | Le Calyra Book 14 a combien de RAM ? | Ordinateur portable Calyra Book 14 (CAL-BOOK-14) coûte 2899.000 TND, avec une garantie de 24 mois. Il est en stock. | missing number 16 |
| `stock-en-03` | Can I buy 5 Orbix Lite phones? | Our assistant is temporarily limited. The most relevant section of our documents is "Brightcart Electronics: Product Catalogue (November 2026)": «6.5-inch AMOLE | missing number 3; tools called [], expected ['check_stock'] / forbidden []; tool statuses {}, expected {'check_stock': ['success']} |
| `stock-fr-02` | Avez-vous la tablette Zelko Tab 10 en stock ? | Tablette Zelko Tab 10 128 Go (ZEL-TAB-10) est en stock. | answered in en, expected fr |
| `unk-en-02` | Will the Orbix X6 be released next month? | Our assistant is temporarily limited. The most relevant section of our documents is "Brightcart Electronics: Product Catalogue (November 2026)": «6.5-inch AMOLE | outcome answered not in ['unknown'] |
| `unk-tn-01` | فما تخفيضات نهار الجمعة السوداء؟ | شنوة المنتوج اللي تحكي عليه؟ عطيني الإسم متاعو ولا الرمز. | outcome needs_info not in ['unknown'] |
