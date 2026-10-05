"""How a supplier prints numbers, dates and labels.

The same invoice data reads "1 234,56 €" on a French invoice, "£1,234.56" on a British
one and "1.234,56 EUR" on a German one; "03/04/2026" is April in Paris and March in
Chicago. Ground truth is kept as numbers and dates, and only the rendering applies
these conventions, which is what makes the extraction task non-trivial.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from countersign.datagen.catalog import VendorSpec

_SYMBOLS = {"EUR": "€", "GBP": "£", "USD": "$", "CHF": "CHF"}
_SEPARATORS = {"fr": (" ", ","), "en": (",", "."), "de": (".", ","), "ch": ("'", ".")}

_MONTHS = {
    "fr": "janvier février mars avril mai juin juillet août septembre octobre novembre décembre",
    "en": "January February March April May June July August September October November December",
    "de": "Januar Februar März April Mai Juni Juli August September Oktober November Dezember",
    "es": "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre "
    "diciembre",
    "it": "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre "
    "dicembre",
}

LABELS: dict[str, dict[str, str]] = {
    "fr": {
        "invoice": "FACTURE",
        "credit_note": "AVOIR",
        "quote": "DEVIS",
        "delivery_note": "BON DE LIVRAISON",
        "reminder": "LETTRE DE RELANCE",
        "proforma": "FACTURE PRO FORMA",
        "order_confirmation": "ACCUSÉ DE RÉCEPTION DE COMMANDE",
        "statement": "RELEVÉ DE COMPTE",
        "number": "Facture n°",
        "number_alt": "Numéro de facture",
        "credit_number": "Avoir n°",
        "doc_number": "N°",
        "date": "Date",
        "date_alt": "Date de facturation",
        "due_date": "Échéance",
        "due_date_alt": "Date d'échéance",
        "validity": "Valable jusqu'au",
        "customer": "Client",
        "bill_to": "Facturé à",
        "customer_no": "Code client",
        "customer_vat": "N° TVA client",
        "supplier_vat": "N° TVA intracommunautaire",
        "supplier_vat_short": "TVA",
        "registration": "SIRET",
        "po": "Votre commande",
        "po_alt": "Référence commande",
        "delivery_ref": "Bon de livraison",
        "original_invoice": "Facture d'origine",
        "description": "Désignation",
        "quantity": "Qté",
        "unit": "Unité",
        "unit_price": "P.U. HT",
        "amount": "Montant HT",
        "vat_col": "TVA",
        "lines_total": "Total lignes HT",
        "allowance": "Remise",
        "charge": "Frais de port",
        "total_net": "Total HT",
        "vat": "TVA",
        "vat_base": "Base HT",
        "vat_amount": "Montant TVA",
        "vat_rate": "Taux",
        "total_tax": "Total TVA",
        "total_gross": "Total TTC",
        "total_gross_alt": "Net à payer",
        "terms": "Conditions de paiement",
        "terms_text": "Paiement à {days} jours date de facture",
        "terms_receipt": "Paiement à réception de facture",
        "bank": "Coordonnées bancaires",
        "bank_intro": "Règlement par virement",
        "direct_debit": "Règlement par prélèvement automatique à l'échéance",
        "page": "Page",
        "carried": "Report",
        "to_carry": "À reporter",
        "reverse_charge": "Autoliquidation de la TVA - article 283-2 du CGI",
        "no_vat": "TVA non applicable",
        "penalty": (
            "En cas de retard de paiement, pénalité de trois fois le taux d'intérêt légal et "
            "indemnité forfaitaire pour frais de recouvrement de 40 EUR. Pas d'escompte pour "
            "paiement anticipé."
        ),
        "thanks": "Nous vous remercions de votre confiance.",
        "duplicate": "DUPLICATA",
        "amounts_in": "Montants exprimés en {currency}",
        "quote_note": "Devis gratuit, valable 30 jours. Bon pour accord, date et signature :",
        "delivery_note_note": "Marchandise reçue en bon état. Signature du destinataire :",
        "reminder_note": (
            "Sauf erreur de notre part, la facture ci-dessous reste impayée à ce jour. Nous vous "
            "remercions de procéder à son règlement sous huit jours. Ce courrier n'est pas une "
            "facture."
        ),
        "proforma_note": (
            "Document sans valeur comptable, établi pour information. La facture définitive "
            "sera émise à l'expédition."
        ),
        "order_note": (
            "Nous accusons réception de votre commande. Ce document n'est pas une facture."
        ),
        "new_bank": (
            "ATTENTION : nos coordonnées bancaires ont changé. Merci d'utiliser ce nouvel IBAN."
        ),
    },
    "en": {
        "invoice": "INVOICE",
        "credit_note": "CREDIT NOTE",
        "quote": "QUOTATION",
        "delivery_note": "DELIVERY NOTE",
        "reminder": "PAYMENT REMINDER",
        "proforma": "PRO FORMA INVOICE",
        "order_confirmation": "ORDER CONFIRMATION",
        "statement": "STATEMENT OF ACCOUNT",
        "number": "Invoice No.",
        "number_alt": "Invoice #",
        "credit_number": "Credit Note No.",
        "doc_number": "No.",
        "date": "Date",
        "date_alt": "Invoice date",
        "due_date": "Due date",
        "due_date_alt": "Payment due",
        "validity": "Valid until",
        "customer": "Customer",
        "bill_to": "Bill To",
        "customer_no": "Account No.",
        "customer_vat": "Customer VAT No.",
        "supplier_vat": "VAT Reg. No.",
        "supplier_vat_short": "VAT No.",
        "registration": "Company No.",
        "po": "Your PO",
        "po_alt": "Purchase order",
        "delivery_ref": "Delivery note",
        "original_invoice": "Original invoice",
        "description": "Description",
        "quantity": "Qty",
        "unit": "Unit",
        "unit_price": "Unit price",
        "amount": "Amount",
        "vat_col": "VAT",
        "lines_total": "Subtotal",
        "allowance": "Discount",
        "charge": "Shipping",
        "total_net": "Net total",
        "vat": "VAT",
        "vat_base": "Net",
        "vat_amount": "VAT amount",
        "vat_rate": "Rate",
        "total_tax": "Total VAT",
        "total_gross": "Total due",
        "total_gross_alt": "Invoice total",
        "terms": "Payment terms",
        "terms_text": "Net {days} days from invoice date",
        "terms_receipt": "Due on receipt",
        "bank": "Bank details",
        "bank_intro": "Please remit by bank transfer",
        "direct_debit": "Collected by direct debit on the due date",
        "page": "Page",
        "carried": "Brought forward",
        "to_carry": "Carried forward",
        "reverse_charge": "Reverse charge: VAT to be accounted for by the recipient",
        "no_vat": "Zero-rated export supply",
        "penalty": (
            "Late payments are subject to interest at 8% above base rate and a fixed recovery "
            "charge of 40.00. No early settlement discount."
        ),
        "thanks": "Thank you for your business.",
        "duplicate": "COPY",
        "amounts_in": "All amounts in {currency}",
        "quote_note": "This quotation is valid for 30 days. Accepted by (name, date, signature):",
        "delivery_note_note": "Goods received in good condition. Receiver's signature:",
        "reminder_note": (
            "According to our records the invoice below remains unpaid. Please arrange payment "
            "within eight days. This letter is not an invoice."
        ),
        "proforma_note": (
            "This document is not a tax invoice. A final invoice will be issued on dispatch."
        ),
        "order_note": "We acknowledge receipt of your order. This document is not an invoice.",
        "new_bank": "IMPORTANT: our bank details have changed. Please use this new IBAN.",
    },
    "de": {
        "invoice": "RECHNUNG",
        "credit_note": "GUTSCHRIFT",
        "quote": "ANGEBOT",
        "delivery_note": "LIEFERSCHEIN",
        "reminder": "ZAHLUNGSERINNERUNG",
        "proforma": "PROFORMA-RECHNUNG",
        "order_confirmation": "AUFTRAGSBESTÄTIGUNG",
        "statement": "KONTOAUSZUG",
        "number": "Rechnungsnummer",
        "number_alt": "Rechnung Nr.",
        "credit_number": "Gutschrift Nr.",
        "doc_number": "Nr.",
        "date": "Datum",
        "date_alt": "Rechnungsdatum",
        "due_date": "Fällig am",
        "due_date_alt": "Zahlbar bis",
        "validity": "Gültig bis",
        "customer": "Kunde",
        "bill_to": "Rechnungsempfänger",
        "customer_no": "Kundennummer",
        "customer_vat": "USt-IdNr. Kunde",
        "supplier_vat": "USt-IdNr.",
        "supplier_vat_short": "USt-IdNr.",
        "registration": "Steuernummer",
        "po": "Ihre Bestellung",
        "po_alt": "Bestellnummer",
        "delivery_ref": "Lieferschein",
        "original_invoice": "Ursprüngliche Rechnung",
        "description": "Bezeichnung",
        "quantity": "Menge",
        "unit": "Einheit",
        "unit_price": "Einzelpreis",
        "amount": "Gesamt",
        "vat_col": "MwSt",
        "lines_total": "Zwischensumme",
        "allowance": "Rabatt",
        "charge": "Versandkosten",
        "total_net": "Nettobetrag",
        "vat": "MwSt",
        "vat_base": "Netto",
        "vat_amount": "MwSt-Betrag",
        "vat_rate": "Satz",
        "total_tax": "Umsatzsteuer gesamt",
        "total_gross": "Rechnungsbetrag",
        "total_gross_alt": "Gesamtbetrag",
        "terms": "Zahlungsbedingungen",
        "terms_text": "Zahlbar innerhalb von {days} Tagen ohne Abzug",
        "terms_receipt": "Zahlbar sofort nach Erhalt",
        "bank": "Bankverbindung",
        "bank_intro": "Bitte überweisen Sie den Betrag auf folgendes Konto",
        "direct_debit": "Der Betrag wird per Lastschrift eingezogen",
        "page": "Seite",
        "carried": "Übertrag",
        "to_carry": "Übertrag",
        "reverse_charge": "Steuerfreie innergemeinschaftliche Lieferung (§ 4 Nr. 1b UStG)",
        "no_vat": "Steuerfreie Ausfuhrlieferung",
        "penalty": (
            "Bei Zahlungsverzug berechnen wir Verzugszinsen sowie eine Pauschale von 40,00 EUR."
        ),
        "thanks": "Vielen Dank für Ihren Auftrag.",
        "duplicate": "KOPIE",
        "amounts_in": "Alle Beträge in {currency}",
        "quote_note": "Dieses Angebot ist 30 Tage gültig.",
        "delivery_note_note": "Ware in einwandfreiem Zustand erhalten. Unterschrift:",
        "reminder_note": (
            "Die folgende Rechnung ist noch offen. Dieses Schreiben ist keine Rechnung."
        ),
        "proforma_note": "Dieses Dokument ist keine Rechnung im Sinne des UStG.",
        "order_note": "Wir bestätigen Ihren Auftrag. Dieses Dokument ist keine Rechnung.",
        "new_bank": "ACHTUNG: Unsere Bankverbindung hat sich geändert. Bitte neue IBAN verwenden.",
    },
    "es": {
        "invoice": "FACTURA",
        "credit_note": "FACTURA RECTIFICATIVA",
        "quote": "PRESUPUESTO",
        "delivery_note": "ALBARÁN",
        "reminder": "RECORDATORIO DE PAGO",
        "proforma": "FACTURA PROFORMA",
        "order_confirmation": "CONFIRMACIÓN DE PEDIDO",
        "statement": "EXTRACTO DE CUENTA",
        "number": "Factura n.º",
        "number_alt": "Número de factura",
        "credit_number": "Rectificativa n.º",
        "doc_number": "N.º",
        "date": "Fecha",
        "date_alt": "Fecha de factura",
        "due_date": "Vencimiento",
        "due_date_alt": "Fecha de vencimiento",
        "validity": "Válido hasta",
        "customer": "Cliente",
        "bill_to": "Facturar a",
        "customer_no": "Código de cliente",
        "customer_vat": "NIF-IVA cliente",
        "supplier_vat": "NIF-IVA",
        "supplier_vat_short": "NIF",
        "registration": "CIF",
        "po": "Su pedido",
        "po_alt": "Número de pedido",
        "delivery_ref": "Albarán",
        "original_invoice": "Factura original",
        "description": "Descripción",
        "quantity": "Cant.",
        "unit": "Ud.",
        "unit_price": "Precio",
        "amount": "Importe",
        "vat_col": "IVA",
        "lines_total": "Subtotal",
        "allowance": "Descuento",
        "charge": "Portes",
        "total_net": "Base imponible",
        "vat": "IVA",
        "vat_base": "Base",
        "vat_amount": "Cuota",
        "vat_rate": "Tipo",
        "total_tax": "Total IVA",
        "total_gross": "Total factura",
        "total_gross_alt": "Total a pagar",
        "terms": "Forma de pago",
        "terms_text": "Transferencia a {days} días fecha factura",
        "terms_receipt": "Pago al contado",
        "bank": "Datos bancarios",
        "bank_intro": "Pago por transferencia bancaria",
        "direct_debit": "Recibo domiciliado al vencimiento",
        "page": "Página",
        "carried": "Suma anterior",
        "to_carry": "Suma y sigue",
        "reverse_charge": "Operación exenta - entrega intracomunitaria (art. 25 Ley 37/1992)",
        "no_vat": "Operación exenta de IVA",
        "penalty": (
            "El impago en plazo devengará intereses de demora y 40,00 EUR de costes de cobro."
        ),
        "thanks": "Gracias por su confianza.",
        "duplicate": "DUPLICADO",
        "amounts_in": "Importes en {currency}",
        "quote_note": "Presupuesto válido durante 30 días.",
        "delivery_note_note": "Mercancía recibida conforme. Firma:",
        "reminder_note": (
            "La siguiente factura sigue pendiente de pago. Este escrito no es una factura."
        ),
        "proforma_note": "Documento sin validez fiscal.",
        "order_note": "Confirmamos su pedido. Este documento no es una factura.",
        "new_bank": "ATENCIÓN: nuestros datos bancarios han cambiado. Utilice este nuevo IBAN.",
    },
    "it": {
        "invoice": "FATTURA",
        "credit_note": "NOTA DI CREDITO",
        "quote": "PREVENTIVO",
        "delivery_note": "DOCUMENTO DI TRASPORTO",
        "reminder": "SOLLECITO DI PAGAMENTO",
        "proforma": "FATTURA PROFORMA",
        "order_confirmation": "CONFERMA D'ORDINE",
        "statement": "ESTRATTO CONTO",
        "number": "Fattura n.",
        "number_alt": "Numero fattura",
        "credit_number": "Nota di credito n.",
        "doc_number": "N.",
        "date": "Data",
        "date_alt": "Data fattura",
        "due_date": "Scadenza",
        "due_date_alt": "Data di scadenza",
        "validity": "Valido fino al",
        "customer": "Cliente",
        "bill_to": "Destinatario",
        "customer_no": "Codice cliente",
        "customer_vat": "P.IVA cliente",
        "supplier_vat": "Partita IVA",
        "supplier_vat_short": "P.IVA",
        "registration": "Codice fiscale",
        "po": "Vs. ordine",
        "po_alt": "Numero d'ordine",
        "delivery_ref": "DDT",
        "original_invoice": "Fattura originale",
        "description": "Descrizione",
        "quantity": "Q.tà",
        "unit": "U.M.",
        "unit_price": "Prezzo",
        "amount": "Importo",
        "vat_col": "IVA",
        "lines_total": "Totale merce",
        "allowance": "Sconto",
        "charge": "Spese di trasporto",
        "total_net": "Imponibile",
        "vat": "IVA",
        "vat_base": "Imponibile",
        "vat_amount": "Imposta",
        "vat_rate": "Aliquota",
        "total_tax": "Totale IVA",
        "total_gross": "Totale fattura",
        "total_gross_alt": "Totale da pagare",
        "terms": "Condizioni di pagamento",
        "terms_text": "Bonifico bancario {days} giorni data fattura",
        "terms_receipt": "Pagamento a vista fattura",
        "bank": "Coordinate bancarie",
        "bank_intro": "Pagamento tramite bonifico bancario",
        "direct_debit": "Addebito diretto alla scadenza",
        "page": "Pagina",
        "carried": "Riporto",
        "to_carry": "A riportare",
        "reverse_charge": "Operazione non imponibile art. 41 D.L. 331/93 - inversione contabile",
        "no_vat": "Operazione non imponibile",
        "penalty": "In caso di ritardo saranno applicati interessi di mora e 40,00 EUR di spese.",
        "thanks": "Grazie per la fiducia.",
        "duplicate": "COPIA",
        "amounts_in": "Importi in {currency}",
        "quote_note": "Preventivo valido 30 giorni.",
        "delivery_note_note": "Merce ricevuta in buono stato. Firma:",
        "reminder_note": "La seguente fattura risulta non pagata. La presente non è una fattura.",
        "proforma_note": "Documento privo di validità fiscale.",
        "order_note": "Confermiamo il Vs. ordine. Il presente documento non è una fattura.",
        "new_bank": "ATTENZIONE: le nostre coordinate bancarie sono cambiate. Usare il nuovo IBAN.",
    },
}


def quantize(value: Decimal, places: int = 2) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def number(value: Decimal, style: str, places: int | None = 2) -> str:
    """Print `value` with the supplier's separators; `places=None` keeps its own scale."""
    if places is not None:
        value = quantize(value, places)
    sign = "-" if value < 0 else ""
    integer, _, fraction = f"{abs(value):f}".partition(".")
    grouping, decimal = _SEPARATORS[style]
    groups: list[str] = []
    while len(integer) > 3:
        groups.insert(0, integer[-3:])
        integer = integer[:-3]
    groups.insert(0, integer)
    text = grouping.join(groups)
    return f"{sign}{text}{decimal}{fraction}" if fraction else f"{sign}{text}"


def money(value: Decimal, spec: VendorSpec) -> str:
    """Print an amount the way the supplier prints a total."""
    text = number(value, spec.number_style)
    symbol = _SYMBOLS[spec.currency]
    match spec.amount_style:
        case "prefix_symbol" if symbol != spec.currency:
            return f"-{symbol}{text[1:]}" if text.startswith("-") else f"{symbol}{text}"
        case "suffix_symbol":
            return f"{text} {symbol}"
        case "bare":
            return text
        case _:
            return f"{text} {spec.currency}"


def rate(value: Decimal, spec: VendorSpec) -> str:
    """Print a VAT rate: "20 %", "5,5 %", "19%"."""
    text = number(value, spec.number_style, places=None)
    return f"{text}%" if spec.language == "en" else f"{text} %"


def day(value: date, spec: VendorSpec) -> str:
    months = _MONTHS[spec.language].split()
    match spec.date_style:
        case "dmy_slash":
            return value.strftime("%d/%m/%Y")
        case "dmy_dot":
            return value.strftime("%d.%m.%Y")
        case "dmy_dash":
            return value.strftime("%d-%m-%Y")
        case "mdy_slash":
            return value.strftime("%m/%d/%Y")
        case "iso":
            return value.isoformat()
        case "mdy_text":
            return f"{months[value.month - 1]} {value.day}, {value.year}"
        case "dmy_text":
            month = months[value.month - 1]
            if spec.language == "es":
                return f"{value.day} de {month} de {value.year}"
            if spec.language == "de":
                return f"{value.day}. {month} {value.year}"
            return f"{value.day} {month} {value.year}"
        case _:
            raise ValueError(f"unknown date style: {spec.date_style}")


def labels(spec: VendorSpec) -> dict[str, str]:
    return LABELS[spec.language]
