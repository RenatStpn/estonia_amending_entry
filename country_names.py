"""
Translates the Estonian row labels ssb.ee returns in its by-country revenue
table (country names, plus a couple of aggregate rows like "Eksport kokku")
into English.

Country names are translated via Babel's CLDR data (Estonian name -> ISO
country code -> English name) rather than a hand-typed list, so the mapping
is complete and accurate. A small manual table covers ssb.ee's non-country
aggregate rows and the rare territory CLDR doesn't have a current name for.
"""
from babel import Locale

_et_territories = Locale("et").territories
_en_territories = Locale("en").territories
_et_name_to_code = {name: code for code, name in _et_territories.items()}

# Aggregate/summary rows ssb.ee shows alongside actual countries, and
# territories not covered by current CLDR data.
_MANUAL_OVERRIDES = {
    "Müük kokku": "Total sales",
    "Eksport kokku": "Total exports",
    "Muud EU sisesed riigid": "Other EU countries",
    "Muud riigid": "Other countries",
    "Hollandi Antillid": "Netherlands Antilles",
}


def translate(estonian_name):
    """Best-effort Estonian -> English translation. Falls back to the
    original string, unchanged, if there's no known mapping — so an
    unrecognized label is still shown rather than dropped or erroring."""
    if estonian_name in _MANUAL_OVERRIDES:
        return _MANUAL_OVERRIDES[estonian_name]

    code = _et_name_to_code.get(estonian_name)
    if code:
        english = _en_territories.get(code)
        if english:
            return english

    return estonian_name
