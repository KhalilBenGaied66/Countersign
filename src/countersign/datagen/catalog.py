"""The fictional buyer, its suppliers and what they sell.

Everything here is invented. Identifiers (SIREN, SIRET, VAT, IBAN) are generated with
valid check digits from a seed derived from the supplier key, so they are stable from
one run to the next and belong to no real company.

`split` says where a supplier appears: "dev" suppliers are used in both dataset splits,
"test" suppliers only in the held-out split. Layouts and languages follow the supplier,
so holding a supplier out also holds out how its invoices look.
"""

import random
from dataclasses import dataclass, field
from typing import Literal

from countersign.datagen import ids

Layout = Literal["classic", "columns", "ledger", "anglo", "footer_ids", "german", "compact"]
VatMode = Literal["domestic", "reverse_charge", "none"]

DEV_LAYOUTS: frozenset[str] = frozenset({"classic", "columns", "ledger", "anglo"})
DEV_LANGUAGES: frozenset[str] = frozenset({"fr", "en"})


@dataclass(frozen=True)
class Item:
    description: str
    price: tuple[float, float]
    quantity: tuple[float, float] = (1, 12)
    unit: str = ""
    quantity_decimals: int = 0
    vat_rate: str = "20"
    price_decimals: int = 2


@dataclass(frozen=True)
class VendorSpec:
    key: str
    name: str
    country: str
    language: str
    address: tuple[str, ...]
    layout: Layout
    number_pattern: str
    items: tuple[Item, ...]
    currency: str = "EUR"
    number_style: Literal["fr", "en", "de", "ch"] = "fr"
    date_style: str = "dmy_slash"
    amount_style: Literal["suffix_symbol", "prefix_symbol", "code", "bare"] = "suffix_symbol"
    terms_days: int = 30
    po_required: bool = False
    vat_mode: VatMode = "domestic"
    prints_iban: bool = True
    prints_due_date: bool = True
    split: Literal["dev", "test"] = "dev"
    in_master: bool = True
    font: Literal["Helvetica", "Times-Roman", "Courier"] = "Helvetica"
    accent: str = "#1f3a5f"
    credit_sign: Literal["positive", "negative"] = "positive"
    contact: str = ""
    legal: str = ""


@dataclass(frozen=True)
class Vendor:
    """A supplier with its generated identifiers."""

    spec: VendorSpec
    vendor_id: str
    vat_id: str | None
    siret: str | None
    iban: str | None
    bic: str | None

    @property
    def name(self) -> str:
        return self.spec.name


@dataclass(frozen=True)
class Company:
    """The buyer: the company that receives the invoices."""

    name: str = "Orvane Industries SAS"
    address: tuple[str, ...] = ("18 rue des Frères Voisin", "69007 Lyon", "France")
    vat_id: str = field(default="")
    siret: str = field(default="")
    ibans: tuple[str, ...] = ()
    po_pattern: str = r"PO-20\d{2}-\d{5}"
    po_example: str = "PO-2026-00123"


def _fr(*lines: str) -> tuple[str, ...]:
    return (*lines, "France")


SPECS: tuple[VendorSpec, ...] = (
    # --- French suppliers used in both splits -------------------------------------
    VendorSpec(
        key="breval",
        name="Bréval Roulements SAS",
        country="FR",
        language="fr",
        address=_fr("42 rue Francis de Pressensé", "69100 Villeurbanne"),
        layout="classic",
        number_pattern="FA-{year}-{seq:05d}",
        po_required=True,
        accent="#1f3a5f",
        contact="Tél. 04 72 00 41 18 - compta@breval-roulements.example",
        legal="SAS au capital de 250 000 EUR - RCS Lyon",
        items=(
            Item("Roulement à billes 6204-2RS", (3.2, 6.8), (10, 200)),
            Item("Roulement à rouleaux coniques 30206", (11.5, 19.9), (4, 60)),
            Item("Palier à semelle UCP 205", (14.0, 27.5), (2, 40)),
            Item("Courroie trapézoïdale SPZ 1250", (8.9, 13.4), (2, 30)),
            Item("Joint à lèvre 35x52x7", (1.1, 2.9), (10, 150)),
            Item("Graisse lithium EP2 - cartouche 400 g", (4.5, 7.9), (6, 48)),
            Item("Chaîne à rouleaux 08B-1 (5 m)", (28.0, 46.0), (1, 12)),
        ),
    ),
    VendorSpec(
        key="forez",
        name="Cartonnages du Forez SARL",
        country="FR",
        language="fr",
        address=_fr("ZI de Molina la Chazotte", "42000 Saint-Étienne"),
        layout="columns",
        number_pattern="{yy}{mm}-{seq:04d}",
        date_style="dmy_text",
        amount_style="bare",
        terms_days=45,
        accent="#7a4a12",
        font="Times-Roman",
        contact="contact@cartonnages-forez.example",
        legal="SARL au capital de 80 000 EUR - RCS Saint-Étienne",
        items=(
            Item("Caisse américaine double cannelure 600x400x400", (1.35, 2.1), (100, 1500)),
            Item("Caisse carton simple cannelure 400x300x200", (0.48, 0.92), (200, 2500)),
            Item("Film étirable manuel 450 mm x 300 m", (5.2, 8.4), (6, 120)),
            Item("Ruban adhésif PP havane 50 mm x 100 m", (0.95, 1.6), (36, 360)),
            Item("Cornière carton 35x35x1000", (0.31, 0.55), (100, 1000)),
            Item("Palette bois 800x1200 légère", (6.9, 11.5), (10, 80)),
        ),
    ),
    VendorSpec(
        key="vallier",
        name="Transports Vallier & Fils SAS",
        country="FR",
        language="fr",
        address=_fr("7 chemin du Lortaret", "69960 Corbas"),
        layout="ledger",
        number_pattern="F{yy}{mm}{seq:04d}",
        amount_style="code",
        terms_days=30,
        font="Courier",
        accent="#000000",
        credit_sign="negative",
        contact="exploitation@transports-vallier.example",
        legal="SAS au capital de 120 000 EUR - RCS Lyon",
        items=(
            Item("Transport lot complet Lyon - Lille", (780.0, 960.0), (1, 3)),
            Item("Transport messagerie palette 80x120", (48.0, 96.0), (1, 14)),
            Item("Livraison avec hayon", (22.0, 38.0), (1, 6)),
            Item("Immobilisation véhicule", (55.0, 70.0), (0.5, 4), "h", 2),
            Item("Surcharge carburant", (12.0, 64.0), (1, 1)),
            Item("Location semi-remorque", (140.0, 185.0), (1, 5), "jour"),
        ),
    ),
    VendorSpec(
        key="infralog",
        name="Infralog Systèmes SAS",
        country="FR",
        language="fr",
        address=_fr("12 avenue Doyen Louis Weil", "38000 Grenoble"),
        layout="classic",
        number_pattern="{year}-{seq:04d}",
        date_style="dmy_text",
        amount_style="code",
        po_required=True,
        accent="#0b6e4f",
        contact="facturation@infralog.example - 04 76 00 12 90",
        legal="SAS au capital de 60 000 EUR - RCS Grenoble",
        items=(
            Item("Prestation d'intégration ERP", (640.0, 820.0), (1, 12), "jour", 1),
            Item("Maintenance applicative mensuelle", (1200.0, 2400.0), (1, 1)),
            Item("Licence utilisateur nommé (annuelle)", (180.0, 320.0), (2, 40)),
            Item("Hébergement serveur dédié", (310.0, 520.0), (1, 3), "mois"),
            Item("Assistance téléphonique", (85.0, 110.0), (1, 14), "h", 2),
        ),
    ),
    VendorSpec(
        key="dufresne",
        name="Atelier Mécanique Dufresne EURL",
        country="FR",
        language="fr",
        address=_fr("315 rue de la Plasturgie", "01100 Oyonnax"),
        layout="columns",
        number_pattern="AMD/{year}/{seq:03d}",
        terms_days=45,
        prints_due_date=False,
        accent="#5a2a82",
        contact="atelier@dufresne-meca.example",
        legal="EURL au capital de 15 000 EUR - RCS Bourg-en-Bresse",
        items=(
            Item("Usinage bride inox 316L selon plan P-2291", (38.0, 92.0), (2, 60)),
            Item("Tournage axe Ø40 L=220 acier 42CD4", (24.0, 51.0), (4, 80)),
            Item("Fraisage platine aluminium 200x150x12", (31.0, 66.0), (2, 40)),
            Item("Reprise soudure TIG", (58.0, 72.0), (1, 9), "h", 1),
            Item("Contrôle tridimensionnel avec rapport", (120.0, 190.0), (1, 2)),
        ),
    ),
    VendorSpec(
        key="securipro",
        name="Sécuripro Équipements SARL",
        country="FR",
        language="fr",
        address=_fr("ZAC des Gaulnes, 3 allée du Rhône", "69330 Meyzieu"),
        layout="classic",
        number_pattern="FC{seq:06d}",
        accent="#b3261e",
        prints_iban=False,
        contact="www.securipro-equipements.example",
        legal="SARL au capital de 40 000 EUR - RCS Lyon",
        items=(
            Item("Gants de manutention nitrile taille 9 (paire)", (1.9, 3.6), (12, 240)),
            Item("Chaussures de sécurité S3 pointure 43", (39.0, 68.0), (1, 20)),
            Item("Lunettes de protection incolores", (2.8, 6.4), (10, 100)),
            Item("Casque de chantier avec jugulaire", (9.5, 17.0), (2, 40)),
            Item("Gilet haute visibilité classe 2", (3.4, 6.2), (5, 80)),
            Item("Bouchons d'oreille (boîte de 200)", (18.0, 27.0), (1, 12)),
        ),
    ),
    VendorSpec(
        key="interim",
        name="Intérim Alpes Travail Temporaire SAS",
        country="FR",
        language="fr",
        address=_fr("88 cours Lafayette", "69003 Lyon"),
        layout="ledger",
        number_pattern="{seq:07d}",
        terms_days=30,
        font="Courier",
        accent="#000000",
        contact="agence.lyon@interim-alpes.example",
        legal="SAS au capital de 500 000 EUR - RCS Lyon",
        items=(
            Item("Cariste CACES 3 - semaine 11", (27.4, 31.9), (7, 39), "h", 2),
            Item("Opérateur de conditionnement - semaine 11", (23.1, 25.8), (7, 39), "h", 2),
            Item("Heures supplémentaires 25 %", (30.2, 34.6), (1, 8), "h", 2),
            Item("Indemnité de panier", (7.1, 9.4), (1, 5)),
            Item("Technicien de maintenance - semaine 12", (34.5, 41.0), (7, 35), "h", 2),
        ),
    ),
    VendorSpec(
        key="savoie",
        name="Aciers Laminés de Savoie SA",
        country="FR",
        language="fr",
        address=_fr("1 quai de l'Isère", "73200 Albertville"),
        layout="columns",
        number_pattern="ALS-{seq:06d}",
        terms_days=60,
        po_required=True,
        accent="#3d3d3d",
        contact="adv@aciers-savoie.example",
        legal="SA au capital de 1 200 000 EUR - RCS Chambéry",
        items=(
            Item("Tôle acier S235 laminée à chaud 3 mm", (0.92, 1.38), (120, 2400), "kg", 1),
            Item("Rond acier étiré C45 Ø30", (1.15, 1.72), (40, 900), "kg", 1),
            Item("Tube carré 40x40x3 S235", (4.6, 7.2), (12, 240), "m", 1),
            Item("Cornière à ailes égales 50x50x5", (3.9, 5.8), (12, 180), "m", 1),
            Item("Découpe à longueur", (1.2, 2.4), (4, 60)),
            Item("Certificat matière 3.1", (12.0, 18.0), (1, 4)),
        ),
    ),
    VendorSpec(
        key="perrachon",
        name="Maison Perrachon Traiteur SARL",
        country="FR",
        language="fr",
        address=_fr("26 rue de la Charité", "69002 Lyon"),
        layout="classic",
        number_pattern="{seq:05d}-{yy}",
        terms_days=30,
        accent="#8a1c4a",
        font="Times-Roman",
        contact="commandes@maison-perrachon.example",
        legal="SARL au capital de 20 000 EUR - RCS Lyon",
        items=(
            Item("Plateau repas déjeuner", (14.5, 22.0), (6, 40), vat_rate="10"),
            Item("Buffet froid par personne", (19.0, 31.0), (10, 60), vat_rate="10"),
            Item("Eau minérale 1 L", (1.2, 1.9), (6, 48), vat_rate="5.5"),
            Item("Jus de fruits 1 L", (2.4, 3.6), (4, 24), vat_rate="5.5"),
            Item("Vin de pays 75 cl", (7.5, 12.0), (2, 18)),
            Item("Service en salle", (32.0, 38.0), (2, 8), "h", 1),
            Item("Livraison et installation", (25.0, 45.0), (1, 1)),
        ),
    ),
    # --- English-language suppliers used in both splits ---------------------------
    VendorSpec(
        key="northfield",
        name="Northfield Bearings Ltd",
        country="GB",
        language="en",
        address=("Unit 4, Carbrook Trading Estate", "Sheffield S9 2TY", "United Kingdom"),
        layout="anglo",
        number_pattern="INV-{seq:06d}",
        currency="GBP",
        number_style="en",
        date_style="dmy_text",
        amount_style="prefix_symbol",
        vat_mode="none",
        accent="#12355b",
        contact="accounts@northfield-bearings.example | +44 114 000 2218",
        legal="Registered in England and Wales No. 04417756",
        items=(
            Item("Deep groove ball bearing 6306-2Z", (4.1, 7.6), (10, 150)),
            Item("Spherical roller bearing 22212 E", (58.0, 86.0), (1, 12)),
            Item("Pillow block unit SY 40 TF", (31.0, 49.0), (1, 20)),
            Item("Shaft seal 45x62x8 NBR", (1.4, 3.3), (10, 100)),
            Item("Export packing and documentation", (18.0, 35.0), (1, 1)),
        ),
    ),
    VendorSpec(
        key="harlow",
        name="Harlow Precision Tools Inc.",
        country="US",
        language="en",
        address=("2200 Industrial Parkway", "Rockford, IL 61109", "USA"),
        layout="anglo",
        number_pattern="{seq:06d}",
        currency="USD",
        number_style="en",
        date_style="mdy_slash",
        amount_style="prefix_symbol",
        vat_mode="none",
        po_required=True,
        prints_iban=False,
        accent="#7c2d12",
        font="Times-Roman",
        contact="ar@harlowprecision.example | (815) 555-0142",
        legal="Federal Tax ID 36-4412907",
        items=(
            Item('Carbide end mill 1/2" 4-flute', (38.0, 64.0), (2, 40)),
            Item("Indexable insert CNMG 432 (box of 10)", (72.0, 118.0), (1, 15)),
            Item('Collet chuck ER32 3/4"', (95.0, 160.0), (1, 6)),
            Item("Dial test indicator 0.0005 in", (140.0, 210.0), (1, 4)),
            Item("International freight and handling", (60.0, 180.0), (1, 1)),
        ),
    ),
    # --- Held out: suppliers, layouts and languages seen only in the test split ----
    VendorSpec(
        key="netclair",
        name="Netclair Propreté SARL",
        country="FR",
        language="fr",
        address=_fr("9 rue Maryse Bastié", "69500 Bron"),
        layout="footer_ids",
        number_pattern="NC-{yy}-{seq:04d}",
        accent="#0f766e",
        split="test",
        contact="04 78 00 63 27",
        legal="SARL au capital de 30 000 EUR - RCS Lyon",
        items=(
            Item("Nettoyage des bureaux - forfait mensuel", (980.0, 1450.0), (1, 1)),
            Item("Nettoyage atelier - passage hebdomadaire", (165.0, 240.0), (2, 5)),
            Item("Vitrerie intérieure et extérieure", (290.0, 420.0), (1, 1)),
            Item("Remise en état après travaux", (36.0, 44.0), (2, 16), "h", 1),
            Item("Consommables sanitaires", (48.0, 130.0), (1, 2)),
        ),
    ),
    VendorSpec(
        key="energie",
        name="Énergie Rhône Distribution SA",
        country="FR",
        language="fr",
        address=_fr("200 avenue Jean Jaurès", "69007 Lyon"),
        layout="footer_ids",
        number_pattern="{seq:010d}",
        terms_days=15,
        accent="#c2410c",
        split="test",
        prints_iban=False,
        contact="Espace client : pro.energie-rhone.example",
        legal="SA au capital de 8 400 000 EUR - RCS Lyon",
        items=(
            Item("Abonnement électricité 36 kVA", (38.0, 61.0), (1, 1), "mois", vat_rate="5.5"),
            Item(
                "Consommation heures pleines", (0.168, 0.214), (800, 9000), "kWh", price_decimals=4
            ),
            Item(
                "Consommation heures creuses", (0.124, 0.158), (400, 6000), "kWh", price_decimals=4
            ),
            Item("Contribution tarifaire d'acheminement", (9.0, 22.0), (1, 1), vat_rate="5.5"),
            Item(
                "Accise sur l'électricité", (0.021, 0.0325), (1200, 15000), "kWh", price_decimals=4
            ),
        ),
    ),
    VendorSpec(
        key="bureauplus",
        name="Bureau Plus Fournitures SAS",
        country="FR",
        language="fr",
        address=_fr("Parc d'activités des Platières", "69440 Mornant"),
        layout="compact",
        number_pattern="BP{year}{seq:06d}",
        accent="#1d4ed8",
        split="test",
        contact="service.clients@bureauplus.example",
        legal="SAS au capital de 300 000 EUR - RCS Lyon",
        items=(
            Item("Ramette papier A4 80 g (500 feuilles)", (3.4, 5.2), (5, 100)),
            Item("Stylo bille bleu (boîte de 50)", (7.9, 12.5), (1, 10)),
            Item("Classeur à levier dos 80 mm", (1.8, 3.1), (5, 60)),
            Item("Cartouche toner noir compatible 26A", (28.0, 54.0), (1, 12)),
            Item("Agrafeuse de bureau 24/6", (5.5, 11.0), (1, 8)),
            Item("Bloc-notes A5 quadrillé", (0.9, 1.7), (10, 120)),
            Item("Pochettes perforées A4 (boîte de 100)", (3.2, 5.9), (2, 30)),
            Item("Marqueur tableau blanc (pochette de 4)", (3.9, 6.8), (2, 24)),
            Item("Enveloppes C5 blanches (boîte de 500)", (14.0, 22.0), (1, 10)),
            Item("Étiquettes adhésives 105x37 (100 feuilles)", (9.5, 16.0), (1, 15)),
            Item("Chemise cartonnée à élastiques", (0.8, 1.6), (10, 100)),
            Item("Rouleau adhésif transparent 19 mm", (0.6, 1.2), (10, 80)),
            Item("Calculatrice de bureau 12 chiffres", (8.9, 15.0), (1, 6)),
            Item("Corbeille à courrier empilable", (2.4, 4.4), (2, 20)),
            Item("Surligneurs assortis (pochette de 6)", (3.1, 5.4), (2, 24)),
            Item("Ciseaux de bureau 21 cm", (1.9, 3.8), (2, 20)),
        ),
    ),
    VendorSpec(
        key="lemaire",
        name="Cabinet Lemaire & Associés",
        country="FR",
        language="fr",
        address=_fr("54 quai Charles de Gaulle", "69006 Lyon"),
        layout="footer_ids",
        number_pattern="H{year}-{seq:03d}",
        date_style="dmy_text",
        terms_days=30,
        accent="#374151",
        font="Times-Roman",
        split="test",
        contact="secretariat@lemaire-avocats.example",
        legal="SELARL au capital de 100 000 EUR - RCS Lyon - Barreau de Lyon",
        items=(
            Item("Honoraires - consultation droit des contrats", (240.0, 320.0), (1, 9), "h", 1),
            Item("Rédaction de conditions générales d'achat", (1800.0, 3200.0), (1, 1)),
            Item("Frais de déplacement", (45.0, 160.0), (1, 1)),
            Item("Frais de greffe et formalités", (38.0, 95.0), (1, 1)),
        ),
    ),
    VendorSpec(
        key="hydrotechnic",
        name="Hydrotechnic Maintenance SARL",
        country="FR",
        language="fr",
        address=_fr("14 rue de l'Industrie", "38230 Chavanoz"),
        layout="compact",
        number_pattern="HM-{seq:05d}",
        terms_days=45,
        po_required=True,
        accent="#0e7490",
        split="test",
        contact="sav@hydrotechnic.example",
        legal="SARL au capital de 50 000 EUR - RCS Vienne",
        items=(
            Item("Intervention sur presse hydraulique", (72.0, 88.0), (1, 12), "h", 1),
            Item("Flexible hydraulique DN12 L=1500", (24.0, 39.0), (1, 14)),
            Item("Kit de joints vérin Ø80", (42.0, 76.0), (1, 6)),
            Item("Huile hydraulique HV46 (fût 20 L)", (61.0, 94.0), (1, 10)),
            Item("Filtre retour 10 microns", (17.0, 33.0), (1, 12)),
            Item("Distributeur 4/3 CETOP 3", (148.0, 235.0), (1, 4)),
            Item("Frais de déplacement zone 2", (55.0, 85.0), (1, 2)),
            Item("Contrôle de pression et rapport", (90.0, 140.0), (1, 2)),
        ),
    ),
    VendorSpec(
        key="kestrel",
        name="Kestrel Cloud Services Ltd",
        country="IE",
        language="en",
        address=("3 Grand Canal Quay", "Dublin 2, D02 X9F5", "Ireland"),
        layout="footer_ids",
        number_pattern="KCS-{year}-{seq:05d}",
        number_style="en",
        date_style="iso",
        amount_style="prefix_symbol",
        vat_mode="reverse_charge",
        accent="#4338ca",
        split="test",
        prints_iban=False,
        contact="billing@kestrelcloud.example",
        legal="Registered in Ireland No. 612004",
        items=(
            Item(
                "Compute instances - standard tier",
                (0.084, 0.142),
                (700, 9000),
                "h",
                price_decimals=4,
            ),
            Item("Object storage", (0.019, 0.026), (500, 20000), "GB", price_decimals=4),
            Item("Managed database - production plan", (290.0, 640.0), (1, 2)),
            Item("Outbound data transfer", (0.06, 0.09), (100, 6000), "GB", price_decimals=4),
            Item("Business support plan", (120.0, 300.0), (1, 1)),
        ),
    ),
    VendorSpec(
        key="vandijk",
        name="Van Dijk Fasteners B.V.",
        country="NL",
        language="en",
        address=("Nijverheidsweg 21", "3534 AM Utrecht", "The Netherlands"),
        layout="columns",
        number_pattern="{year}{seq:05d}",
        number_style="de",
        date_style="dmy_dash",
        amount_style="code",
        vat_mode="reverse_charge",
        accent="#b45309",
        split="test",
        po_required=True,
        contact="sales@vandijk-fasteners.example",
        legal="KvK 30188214",
        items=(
            Item("Hex bolt DIN 933 M10x40 8.8 zinc (box 200)", (14.0, 23.0), (1, 30)),
            Item("Hex nut DIN 934 M10 (box 500)", (9.0, 16.0), (1, 20)),
            Item("Washer DIN 125 M10 (box 1000)", (6.5, 11.0), (1, 20)),
            Item("Socket cap screw DIN 912 M8x30 12.9 (box 200)", (17.0, 29.0), (1, 25)),
            Item("Threaded rod DIN 975 M12 1 m", (1.9, 3.4), (10, 200)),
        ),
    ),
    VendorSpec(
        key="mueller",
        name="Müller Antriebstechnik GmbH",
        country="DE",
        language="de",
        address=("Industriestraße 48", "70565 Stuttgart", "Deutschland"),
        layout="german",
        number_pattern="RE-{year}-{seq:04d}",
        number_style="de",
        date_style="dmy_dot",
        vat_mode="reverse_charge",
        accent="#111827",
        split="test",
        po_required=True,
        contact="buchhaltung@mueller-antrieb.example | Tel. +49 711 000 4420",
        legal="Amtsgericht Stuttgart HRB 721904 - Geschäftsführer: Jens Müller",
        items=(
            Item("Getriebemotor 0,75 kW i=20", (310.0, 465.0), (1, 6)),
            Item("Frequenzumrichter 1,5 kW 400 V", (240.0, 390.0), (1, 5)),
            Item("Kupplung elastisch Größe 28", (36.0, 58.0), (1, 20)),
            Item("Zahnriemenscheibe 8M-30", (22.0, 41.0), (2, 24)),
            Item("Verpackung und Versand", (18.0, 65.0), (1, 1)),
        ),
    ),
    VendorSpec(
        key="breisgau",
        name="Breisgau Messebau GmbH & Co. KG",
        country="DE",
        language="de",
        address=("Gewerbepark 7", "79110 Freiburg im Breisgau", "Deutschland"),
        layout="german",
        number_pattern="{seq:08d}",
        number_style="de",
        date_style="dmy_dot",
        vat_mode="domestic",
        terms_days=14,
        accent="#14532d",
        font="Times-Roman",
        split="test",
        contact="info@breisgau-messebau.example",
        legal="Amtsgericht Freiburg HRA 704412",
        items=(
            Item("Messestand Standardpaket 12 m²", (1450.0, 2100.0), (1, 1), vat_rate="19"),
            Item("Standreinigung täglich", (38.0, 62.0), (2, 5), "Tag", vat_rate="19"),
            Item("Stromanschluss 3 kW", (165.0, 240.0), (1, 2), vat_rate="19"),
            Item("Ausstellerkatalog Druckexemplar", (14.0, 24.0), (2, 20), vat_rate="7"),
            Item("Bewirtung Standparty", (240.0, 520.0), (1, 1), vat_rate="19"),
        ),
    ),
    VendorSpec(
        key="alpenlogistik",
        name="Alpenlogistik AG",
        country="CH",
        language="de",
        address=("Güterstrasse 115", "4053 Basel", "Schweiz"),
        layout="german",
        number_pattern="{yy}-{seq:05d}",
        currency="CHF",
        number_style="ch",
        date_style="dmy_dot",
        amount_style="code",
        vat_mode="none",
        accent="#991b1b",
        split="test",
        contact="dispo@alpenlogistik.example",
        legal="Handelsregister des Kantons Basel-Stadt",
        items=(
            Item("Transport Basel - Lyon Komplettladung", (880.0, 1240.0), (1, 2)),
            Item("Zollabfertigung Export", (65.0, 110.0), (1, 2)),
            Item("Lagerung Palettenstellplatz", (4.2, 6.8), (10, 120), "Tag"),
            Item("Umschlag pro Palette", (7.5, 12.0), (4, 33)),
        ),
    ),
    VendorSpec(
        key="castilla",
        name="Rodamientos Castilla S.L.",
        country="ES",
        language="es",
        address=("Polígono Industrial San Cristóbal, C/ Cobalto 14", "47012 Valladolid", "España"),
        layout="classic",
        number_pattern="FV-{year}-{seq:04d}",
        number_style="de",
        vat_mode="reverse_charge",
        accent="#9a3412",
        split="test",
        contact="administracion@rodamientos-castilla.example",
        legal="Inscrita en el Registro Mercantil de Valladolid, Tomo 1204",
        items=(
            Item("Rodamiento rígido de bolas 6208-2RS", (5.4, 9.8), (10, 120)),
            Item("Soporte de pie UCP 208", (19.0, 34.0), (2, 30)),
            Item("Retén 40x62x8", (1.3, 2.8), (10, 100)),
            Item("Correa trapezoidal SPA 1500", (9.5, 15.0), (2, 30)),
            Item("Portes y embalaje", (22.0, 58.0), (1, 1)),
        ),
    ),
    VendorSpec(
        key="brenta",
        name="Officine Meccaniche Brenta S.r.l.",
        country="IT",
        language="it",
        address=("Via dell'Artigianato 22", "35010 Limena (PD)", "Italia"),
        layout="columns",
        number_pattern="{seq:04d}/{year}",
        number_style="de",
        terms_days=60,
        vat_mode="reverse_charge",
        accent="#1e3a8a",
        split="test",
        contact="amministrazione@officine-brenta.example",
        legal="Capitale sociale 90.000 EUR i.v. - REA PD 331204",
        items=(
            Item("Albero scanalato acciaio C40 L=450", (64.0, 118.0), (2, 24)),
            Item("Flangia in acciaio inox AISI 304 DN80", (41.0, 77.0), (2, 30)),
            Item("Lavorazione di rettifica", (52.0, 66.0), (1, 12), "h", 1),
            Item("Trattamento termico di tempra", (95.0, 210.0), (1, 2)),
            Item("Imballaggio e trasporto", (30.0, 85.0), (1, 1)),
        ),
    ),
    VendorSpec(
        key="levante",
        name="Servicios Feriales Levante S.A.",
        country="ES",
        language="es",
        address=("Avenida del Puerto 210", "46023 Valencia", "España"),
        layout="footer_ids",
        number_pattern="{seq:06d}",
        number_style="de",
        date_style="dmy_text",
        vat_mode="domestic",
        accent="#065f46",
        split="test",
        contact="clientes@feriales-levante.example",
        legal="Registro Mercantil de Valencia, Hoja V-88213",
        items=(
            Item("Alquiler de almacén temporal", (420.0, 780.0), (1, 2), "mes", vat_rate="21"),
            Item("Montaje de stand en feria", (650.0, 1300.0), (1, 1), vat_rate="21"),
            Item("Cajas de cartón reforzado 60x40x40", (1.2, 2.0), (50, 600), vat_rate="21"),
            Item("Agua embotellada para eventos", (0.6, 1.1), (24, 240), vat_rate="10"),
        ),
    ),
    # --- Not in the vendor master: their invoices must go to review -----------------
    VendorSpec(
        key="fgs",
        name="Fournitures Générales du Sud SARL",
        country="FR",
        language="fr",
        address=_fr("5 boulevard de la Liberté", "13001 Marseille"),
        layout="classic",
        number_pattern="FGS{seq:05d}",
        in_master=False,
        accent="#4b5563",
        contact="contact@fgs-sud.example",
        legal="SARL au capital de 8 000 EUR - RCS Marseille",
        items=(
            Item("Lot de visserie assortie", (18.0, 44.0), (1, 12)),
            Item("Disque à tronçonner 125 mm (boîte de 25)", (16.0, 29.0), (1, 10)),
            Item("Bombe de peinture RAL 7016", (5.5, 9.0), (2, 24)),
        ),
    ),
    VendorSpec(
        key="quickparts",
        name="Quickparts Online Ltd",
        country="GB",
        language="en",
        address=("71 Shelton Street", "London WC2H 9JQ", "United Kingdom"),
        layout="anglo",
        number_pattern="QP-{seq:07d}",
        currency="GBP",
        number_style="en",
        date_style="dmy_slash",
        amount_style="prefix_symbol",
        vat_mode="none",
        in_master=False,
        accent="#6d28d9",
        contact="support@quickparts.example",
        legal="Company No. 11820034",
        items=(
            Item("Replacement drive belt HTD 5M-450", (6.2, 11.0), (1, 12)),
            Item("Proximity sensor M12 PNP", (14.0, 26.0), (1, 10)),
            Item("Express courier", (19.0, 34.0), (1, 1)),
        ),
    ),
    VendorSpec(
        key="technoserv",
        name="TechnoServ Express SAS",
        country="FR",
        language="fr",
        address=_fr("Immeuble Le Mercure, 30 rue du Lac", "69003 Lyon"),
        layout="columns",
        number_pattern="TS-{year}-{seq:04d}",
        in_master=False,
        split="test",
        accent="#be123c",
        contact="facturation@technoserv-express.example",
        legal="SAS au capital de 1 000 EUR - RCS Lyon",
        items=(
            Item("Dépannage informatique sur site", (85.0, 120.0), (1, 6), "h", 1),
            Item("Remplacement disque SSD 1 To", (95.0, 150.0), (1, 4)),
            Item("Forfait déplacement", (39.0, 59.0), (1, 1)),
        ),
    ),
    VendorSpec(
        key="baltic",
        name="Baltic Components GmbH",
        country="DE",
        language="en",
        address=("Hafenstraße 3", "20457 Hamburg", "Germany"),
        layout="footer_ids",
        number_pattern="BC{seq:06d}",
        number_style="en",
        date_style="iso",
        vat_mode="reverse_charge",
        in_master=False,
        split="test",
        accent="#0c4a6e",
        contact="orders@baltic-components.example",
        legal="Registered office Hamburg",
        items=(
            Item("Linear guide rail HGR20 L=1000 mm", (38.0, 62.0), (1, 12)),
            Item("Ball screw SFU1605 L=600 mm", (44.0, 71.0), (1, 8)),
            Item("Shipping DAP Lyon", (28.0, 60.0), (1, 1)),
        ),
    ),
)


def _build_vendor(position: int, spec: VendorSpec) -> Vendor:
    rng = random.Random(f"vendor:{spec.key}")
    siren = ids.siren(rng) if spec.country == "FR" else None
    return Vendor(
        spec=spec,
        vendor_id=f"V-{1001 + position}",
        vat_id=ids.fr_vat(siren) if siren else ids.vat_id(rng, spec.country),
        siret=ids.siret(rng, siren) if siren else None,
        iban=ids.iban(rng, spec.country),
        bic=ids.bic(rng, spec.country) if spec.country != "US" else None,
    )


def _build_company() -> Company:
    rng = random.Random("company:orvane")
    siren = ids.siren(rng)
    own_iban = ids.iban(rng, "FR")
    return Company(
        vat_id=ids.fr_vat(siren),
        siret=ids.siret(rng, siren),
        ibans=(own_iban,) if own_iban else (),
    )


VENDORS: tuple[Vendor, ...] = tuple(_build_vendor(i, spec) for i, spec in enumerate(SPECS))
VENDORS_BY_KEY: dict[str, Vendor] = {vendor.spec.key: vendor for vendor in VENDORS}
COMPANY: Company = _build_company()
