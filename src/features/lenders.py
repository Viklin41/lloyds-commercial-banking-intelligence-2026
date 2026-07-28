"""Who holds the charge: a lender-name dictionary over the harvested charges.

``charges.py`` fetched 558,693 charges and, with them, 572,333 ``persons_entitled``
names. Those names are free text typed by whoever filed the MR01, so "Lloyds Bank
plc", "Lloyds Bank PLC as security agent" and "Lloyds Bank Commercial Finance
Limited" all exist and all mean Lloyds. Nothing downstream can ask "is this our
client" until those strings are collapsed onto institutions.

**This is a dictionary exercise, not a fuzzy-matching project.** Bank lending is
extremely concentrated: the four largest groups are more than half of all charges,
and a few hundred ordered patterns classify 77% of them.
``src/features/matching.py`` exists for the contract-supplier problem where the
join key is a company name with no register behind it; here the population of
lenders is small, stable and known, so an explicit rule list is both cheaper and
auditable, which a similarity score is not.

**Order matters and is the whole design.** The rules are first-match-wins, so:

1. ``lbg_retail`` runs before ``lbg``. Halifax, Black Horse, MBNA, Scottish Widows
   and Lex Autolease are Lloyds Banking Group companies but not *commercial
   lending* ones. The plan draws the LBG boundary at commercial entities, so these
   get their own group rather than being silently counted as ours or silently
   dropped. ``is_lbg`` is False for them, visibly.
2. Bank groups run before the trustee/SPV catch-all, so "Barclays Security Trustee
   Limited" is Barclays and only genuinely third-party trustees (GLAS, Wilmington,
   Kroll) land in ``trustee_spv``.
3. ``natwest`` runs before ``lbg`` so "The Royal Bank of Scotland plc" cannot be
   read as Bank of Scotland. The ``lbg`` pattern also carries a negative lookbehind
   for exactly that, so the two defences are independent - a reordering of this
   list cannot quietly hand RBS's book to Lloyds.

Legacy names are mapped to the group that owns the book today, because the panel
spans charges created as far back as the 1990s and the question we ask of them is
"who does this company borrow from", not "what was that entity called at the time":
Midland Bank -> HSBC, Lloyds TSB -> LBG, Abbey National -> Santander, Yorkshire
Bank -> Virgin Money.

``unclassified`` is reported, never hidden. It is mostly individuals, landlords,
pension trustees and one-off SPVs - real charges that simply have no institution
behind them - and the coverage number is part of the deliverable.
"""

from __future__ import annotations

import re

import pandas as pd

# Groups, in the order the rules are tried. The value is the compiled pattern list.
# Every pattern is matched against the *normalised* name (see `normalise`).
RULES: list[tuple[str, list[str]]] = [
    # --- Lloyds Banking Group, retail/consumer arms: NOT the commercial boundary ---
    ("lbg_retail", [
        r"\bhalifax\b",
        r"\bblack horse\b",
        r"\bmbna\b",
        r"\bscottish widows\b",
        r"\blex autolease\b",
        r"\bcheltenham (and )?gloucester\b",
    ]),
    # --- NatWest Group. Before LBG so RBS can never be read as Bank of Scotland ---
    ("natwest", [
        r"\bnat(ional )?west(minster)?\b",
        r"\broyal bank of scotland\b",
        r"\brbs\b",
        r"\bcoutts\b",
        r"\bulster bank\b",
        r"\blombard north central\b",
        r"\bthe one account\b",
        r"\bmentor services\b",
        r"\btyl\b",
        r"\bwilliams (and )?glyn",  # RBS's old English brand
        r"\broyscot\b",               # Royal Bank Leasing / Royscot Trust
        r"\bwestminster bank\b",      # pre-1968, before the National Westminster merger
    ]),
    # --- Lloyds Banking Group, commercial lending ---
    ("lbg", [
        r"\blloyds bank\b",
        r"\blloyds tsb\b",
        r"\blloyds bowmaker\b",
        r"\blloyds development capital\b",
        r"\blloyds commercial\b",
        # "the governor and company of the bank of scotland" is BoS; "the royal bank
        # of scotland" is not. The lookbehind is the guard, and the natwest block
        # above already claimed the RBS strings anyway.
        r"(?<!royal )\bbank of scotland\b",
        r"\bagricultural mortgage corporation\b",
        r"\bbank of wales\b",   # acquired by Bank of Scotland, so inside LBG today
        r"\bhill samuel\b",     # merged into Lloyds TSB
        # Lloyds' own finance arms under their historical names. These matter more
        # than their volume suggests: every one of them is an LBG relationship that
        # would otherwise read as "not our client".
        r"\bldc (managers|ventures|nominees)\b",  # Lloyds Development Capital
        r"\blloyds udt\b",
        r"\balex lawrie\b",     # Alex Lawrie Factors, later Lloyds TSB Commercial Finance
    ]),
    ("hsbc", [
        r"\bhsbc\b",
        r"\bmidland bank\b",  # HSBC's UK name until 1999
        r"\bfirst direct\b",
        r"\bmarks (and )?spencer financial\b",
    ]),
    ("barclays", [
        r"\bbarclays\b",
        r"\bbarclaycard\b",
        r"\bwoolwich\b",
    ]),
    ("santander", [
        r"\bsantander\b",
        r"\babbey national\b",
        r"\balliance (and )?leicester\b",
        r"\bcater allen\b",
    ]),
    ("virgin_money", [
        r"\bvirgin money\b",
        r"\bclydesdale bank\b",
        r"\byorkshire bank\b",
        r"\bnorthern rock\b",
    ]),
    # --- Challenger and specialist banks -------------------------------------- #
    ("challenger_bank", [
        r"\bshawbrook\b", r"\baldermore\b", r"\bclose brothers\b", r"\boaknorth\b",
        r"\bmetro bank\b", r"\ballica\b", r"\bparagon\b", r"\bcynergy\b",
        r"\bhampshire trust\b", r"\bredwood bank\b", r"\bcambridge (and )?counties\b",
        r"\brecognise bank\b", r"\btriodos\b", r"\bunity trust\b", r"\bstarling bank\b",
        r"\bsecure trust bank\b", r"\bhandelsbanken\b", r"\binvestec\b",
        r"\bco[- ]?operative bank\b", r"\btsb bank\b", r"\bsilicon valley bank\b",
        r"\bnatwest markets\b", r"\bnationwide building society\b",
        r"\b\w+ building society\b", r"\bskipton\b", r"\bshepherds friendly\b",
        r"\bpraetura\b", r"\bthincats\b", r"\bfunding circle\b", r"\biwoca\b",
        r"\bcapital on tap\b", r"\bmarket harborough\b", r"\batom bank\b",
        r"\bonesavings bank\b", r"\binterbay\b", r"\bkent reliance\b",
        r"\bprecise mortgages\b", r"\bcharter court\b", r"\bdunbar bank\b",
        r"\bcapital bank\b", r"\bbank of cyprus\b", r"\bzopa\b", r"\btandem bank\b",
        r"\bgatehouse bank\b", r"\bal rayan\b", r"\bunited trust bank\b",
        r"\bmasthaven\b", r"\bassetz\b", r"\bfleet mortgages\b", r"\blandbay\b",
        r"\bthe mortgage lender\b", r"\bbcrs business\b",
    ]),
    # --- Non-bank asset, invoice and specialist finance ------------------------ #
    ("asset_invoice_finance", [
        r"\bbibby\b", r"\btogether commercial\b", r"\btogether personal\b",
        r"\bultimate finance\b", r"\bigf business\b", r"\bleumi abl\b",
        r"\bsme invoice finance\b", r"\bnucleus\b", r"\barbuthnot\b",
        r"\bhitachi capital\b", r"\bnovuna\b", r"\bventure finance\b",
        r"\bclose invoice\b", r"\bcloseb?rothers invoice\b", r"\bgrenke\b",
        r"\bsiemens financial\b", r"\bde lage landen\b", r"\bbnp paribas leasing\b",
        r"\bshire leasing\b", r"\bwhite oak\b", r"\bcompass business finance\b",
        r"\bkennet equipment\b", r"\btime finance\b", r"\basset advantage\b",
        r"\bforward trust\b", r"\bcapital home loans\b", r"\bthe mortgage works\b",
        r"\bpepper (uk|money)\b", r"\bmetrobank sme\b", r"\bcrown business finance\b",
        r"\btouch financial\b", r"\bmarketfinance\b", r"\bcatalyst business finance\b",
        r"\boptimum finance\b", r"\bpartnership invoice\b", r"\bteam factors\b",
        r"\bregency factors\b", r"\bpulse cashflow\b", r"\bgiant finance\b",
        r"\bcharles street\b",  # Together group's commercial lending vehicle
        r"\brocking horse\b", r"\btime invoice\b", r"\becapital\b",
        r"\btriple point\b", r"\bsprk capital\b", r"\bjust cash flow\b",
        r"\bmarketinvoice\b", r"\bnationwide finance\b", r"\boptimum sme\b",
        r"\bmitsubishi hc capital\b", r"\breward finance\b", r"\bge (commercial|capital)\b",
        r"\bstate securities\b", r"\b4syte\b", r"\btc loans\b",
        r"\bultimate invoice\b", r"\bsimply asset\b", r"\bpraetura asset\b",
        r"\bhaydock finance\b", r"\bcloseb?rothers asset\b", r"\bpeac\b",
        r"\bsociete generale equipment\b", r"\bcabot financial\b", r"\baldermore invoice\b",
        r"\bmaxxia\b", r"\bcbpe\b", r"\bboost capital\b", r"\bfleximize\b",
        r"\bliberis\b", r"\bykk\b", r"\bcompass asset\b", r"\bportman asset\b",
        r"\bgrowth street\b", r"\bfinbiz\b", r"\bgbf capital\b",
        r"\badvantedge\b", r"\bsonovate\b", r"\beuro sales finance\b",
        r"\bgriffin (factors|credit)\b", r"\bpositive cashflow\b",
        r"\bigf\b", r"\bbizcap\b", r"\btallaght financial\b",
        r"\bclosebrothers\b",  # the unspaced filing of Close Brothers
        r"\bnmb heller\b", r"\breward capital\b", r"\bashley commercial\b",
        r"\blendinvest\b", r"\bfunding options\b", r"\bmerchant money\b",
        r"\bparatus\b", r"\bseneca (trade|partners)\b", r"\bkingsway asset\b",
    ]),
    # --- Other banks: foreign, Irish, investment ------------------------------- #
    ("other_bank", [
        r"\baib\b", r"\ballied irish\b", r"\bbank of ireland\b", r"\banglo irish\b",
        r"\bnorthern bank\b", r"\bdanske\b", r"\bpermanent tsb\b",
        r"\bbank of america\b", r"\bcitibank\b", r"\bcitigroup\b", r"\bjpmorgan\b",
        r"\bj\.? ?p\.? morgan\b", r"\bgoldman sachs\b", r"\bmorgan stanley\b",
        r"\bdeutsche bank\b", r"\babn amro\b", r"\bing bank\b", r"\bing asia\b",
        r"\brabobank\b", r"\bbnp paribas\b", r"\bsociete generale\b",
        r"\bcredit suisse\b", r"\bubs\b", r"\bstandard chartered\b",
        r"\bstandard bank\b", r"\bbank leumi\b", r"\bbank hapoalim\b",
        r"\bmizuho\b", r"\bmufg\b", r"\bsumitomo\b", r"\bnational bank of\b",
        r"\bwells fargo\b", r"\bmacquarie\b", r"\bnordea\b", r"\bdanske bank\b",
        r"\bstate bank of india\b", r"\bicici\b", r"\bbank of china\b",
        r"\bbank of baroda\b", r"\bemirates nbd\b", r"\bqatar national\b",
        r"\bcredit agricole\b", r"\bnatixis\b", r"\bbarings\b", r"\b3i (group|plc)\b",
        r"\binvestors in industry\b", r"\bares management\b", r"\bapollo\b",
        r"\bblackrock\b", r"\bpricoa\b", r"\bm g investments?\b",
        r"\bbank of montreal\b", r"\bcomerica\b", r"\bpnc (bank|business|financial)\b",
        r"\bfifth third\b", r"\bsilicon valley\b", r"\bhsbc private\b",
        r"\bcaixa\b", r"\bbanco\b", r"\bunicredit\b", r"\bintesa\b",
        r"\bskandinaviska\b", r"\bdnb bank\b", r"\bkbc bank\b", r"\bbelfius\b",
        r"\bhabib\b", r"\bunion bank\b", r"\bark(le)? capital\b", r"\bbeach point\b",
        r"\bbarings\b", r"\bhayfin\b", r"\bcrescent capital\b", r"\bmuzinich\b",
        r"\bbeechbrook\b", r"\bkartesia\b", r"\bpemberton\b", r"\btosca debt\b",
        r"\broyal bank of canada\b", r"\bcanadian imperial\b", r"\bbank of nova scotia\b",
        r"\bfive arrows\b", r"\brothschild\b", r"\bmaven capital\b",
        r"\btoronto dominion\b", r"\bcommonwealth bank of australia\b",
    ]),
    # --- Insurers and pension trustees. A real class of secured lender in this
    #     data (property and sale-and-leaseback), and neither a bank nor an SPV. -- #
    ("insurer_pension", [
        r"\bscottish insurance corporation\b", r"\baviva\b", r"\bnorwich union\b",
        r"\blegal (and )?general\b", r"\broyal london\b", r"\bphoenix life\b",
        r"\bstandard life\b", r"\bprudential\b", r"\bzurich\b", r"\bcanada life\b",
        r"\brothesay\b", r"\bjust retirement\b", r"\bpension (trustees?|fund)\b",
        r"\btrustees? of the .* pension\b", r"\bthe trustee lloyd s\b",
        r"\bfriends (life|provident)\b", r"\bclerical medical\b", r"\bsun life\b",
        r"\beagle star\b", r"\bscottish equitable\b", r"\bcornhill insurance\b",
    ]),
    # --- Government and public bodies ------------------------------------------ #
    ("government", [
        r"\binnovate uk\b", r"\bbritish business bank\b", r"\bhm revenue\b",
        r"\bsecretary of state\b", r"\bhomes england\b", r"\bhomes and communities\b",
        r"\bscottish enterprise\b", r"\bwelsh (ministers|government)\b",
        r"\bthe coal authority\b", r"\bdepartment for\b", r"\bnorth east finance\b",
        r"\bfw capital\b", r"\bthe mayor and commonalty\b",
        r"\bcreative england\b", r"\bnorthern ireland screen\b",
        r"\bdbw investments\b",          # Development Bank of Wales' lending vehicles
        r"\bfinance wales\b", r"\bdevelopment bank of wales\b",
        r"\b\w+ (city|county|borough|district) council\b", r"\bcouncil of the\b",
        r"\bgreater london authority\b", r"\bcombined authority\b",
        r"\bhighlands and islands enterprise\b", r"\bnorthern powerhouse\b",
        r"\bthe national lottery\b", r"\bbig issue invest\b",
    ]),
    # --- Third-party security trustees and SPVs. Last, so a bank's own trustee
    #     vehicle has already been claimed by that bank's group above. ----------- #
    ("trustee_spv", [
        r"\bglas trust\b", r"\bwilmington trust\b", r"\bkroll trustee\b",
        r"\blucid trustee\b", r"\bu\.? ?s\.? bank trustees\b", r"\bciticorp trustee\b",
        r"\bdeutsche trustee\b", r"\bglobal loan agency\b", r"\bgla services\b",
        r"\bsecurity trustee\b", r"\btrust corporation\b", r"\btrustee services\b",
        r"\bnominees? (limited|ltd)\b", r"\bsecurity agent\b", r"\bcorporate trustee\b",
        r"\blaw debenture\b", r"\bogier\b", r"\bintertrust\b", r"\bmourant\b",
        r"\balter domus\b", r"\bbankers trustee\b", r"\bconnaught administration\b",
        r"\bstructured finance management\b", r"\bsanne\b", r"\btmf trustee\b",
        r"\bcbre loan\b", r"\bwells fargo trust\b", r"\bgreensill\b",
        r"\bas trustee\b", r"\bas agent\b", r"\bfacility agent\b", r"\bloan agency\b",
    ]),
]

COMPILED = [
    (group, [re.compile(p) for p in patterns])
    for group, patterns in RULES
]

GROUPS = [g for g, _ in RULES] + ["unclassified"]

# The only group that counts as "banking with us". Deliberately excludes
# ``lbg_retail``: Halifax lending to a landlord is not a commercial banking
# relationship and treating it as one would inflate every LBG-client count.
LBG_GROUP = "lbg"

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^a-z0-9]+")


def normalise(name: str | None) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    Punctuation is dropped rather than kept because the same institution is filed
    as "AIB Group (UK) p.l.c.", "AIB Group (UK) PLC" and "A.I.B. Group UK plc".
    Every pattern above is written against this normalised form.
    """
    if not name:
        return ""
    return _WS.sub(" ", _PUNCT.sub(" ", str(name).lower())).strip()


def classify(name: str | None) -> str:
    """Lender group for one ``persons_entitled`` name. First rule that matches wins."""
    text = normalise(name)
    if not text:
        return "unclassified"
    for group, patterns in COMPILED:
        for pattern in patterns:
            if pattern.search(text):
                return group
    return "unclassified"


def classify_series(names: pd.Series) -> pd.Series:
    """Vectorised-ish ``classify`` over a column.

    The distinct-name cardinality (~79k) is two orders of magnitude below the row
    count, so classify each distinct string once and map it back rather than
    running 572k regex sweeps.
    """
    lookup = {n: classify(n) for n in names.dropna().unique()}
    return names.map(lookup).fillna("unclassified")


def coverage(flat: pd.DataFrame, group_col: str = "lender_group") -> pd.DataFrame:
    """Share of charge-lender rows falling in each group, classified share last.

    This is the number the plan asks to be reported explicitly: unclassified is a
    known-unknown, not a silent zero.
    """
    counts = flat[group_col].value_counts(dropna=False).rename("rows").to_frame()
    counts["share"] = counts["rows"] / counts["rows"].sum()
    return counts


def top_unclassified(flat: pd.DataFrame, n: int = 50) -> pd.DataFrame:
    """The most frequent names no rule caught - the to-do list for the dictionary."""
    unc = flat.loc[flat["lender_group"] == "unclassified", "lender_name"]
    return (unc.value_counts().head(n).rename("charges").to_frame()
               .reset_index(names="lender_name"))
