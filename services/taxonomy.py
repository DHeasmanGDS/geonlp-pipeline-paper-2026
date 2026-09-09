"""Term taxonomy — assigns mined terms to broad geological categories.

Used by the dossier (`/dossier?term=X`) to break a term's top partners
out by category (lithology / mineralogy / commodity / etc.) instead of
showing one undifferentiated list. Also reusable from any view that
wants to surface "industrial geology context."

This is the v1 implementation — hand-curated lists. The lists are
intentionally broad but not exhaustive; new terms that don't match fall
into the "other" category. Two future iterations are interesting:

- Rule-based classifier: detect category from morphology + suffix
  patterns (terms ending in `-ite` → mineral, two-letter element
  symbols → element, etc.).

- Auto-classification via cooccurrence bootstrap: for an unclassified
  term, look at the categories of its top NPMI partners and assign by
  majority. This requires no manual curation and "emerges" the
  taxonomy from the data — see ARCHITECTURE_REVIEW.md item 23.

For now, edit the lists below to fix misclassifications or extend
coverage.
"""

from __future__ import annotations

from typing import Iterable


# ---------------------------------------------------------------------
# Category lists
# ---------------------------------------------------------------------
# All values lower-cased to match the normalization the worker applies
# at mining time. Order within each set doesn't matter.

CATEGORIES: dict[str, set[str]] = {
    "commodity": {
        # Precious metals
        "gold", "silver", "platinum", "palladium", "rhodium", "ruthenium",
        "iridium", "osmium",
        # Base metals
        "copper", "lead", "zinc", "nickel", "tin", "iron", "aluminum",
        "aluminium", "manganese",
        # Battery / energy transition
        "lithium", "cobalt", "graphite", "vanadium",
        # Steel alloys
        "chromium", "tungsten", "molybdenum", "niobium", "tantalum",
        # Critical / strategic
        "indium", "gallium", "germanium", "tellurium", "selenium",
        "scandium", "hafnium", "zirconium", "antimony", "bismuth",
        "cesium", "rubidium", "rhenium", "beryllium",
        # Energy
        "uranium", "thorium", "coal", "oil shale",
        # REE
        "ree", "rare earth", "rare earths", "rare earth elements",
        "lanthanum", "cerium", "praseodymium", "neodymium", "samarium",
        "europium", "gadolinium", "terbium", "dysprosium", "holmium",
        "erbium", "thulium", "ytterbium", "lutetium", "yttrium",
        # Industrial / bulk
        "potash", "phosphate", "salt", "sulfur", "sulphur", "barite",
        "fluorite", "magnesite", "wollastonite", "kaolin", "bentonite",
        # Stones
        "diamond", "ruby", "sapphire", "emerald",
        # Mercury
        "mercury",
    },

    "mineral": {
        # Silicates
        "quartz", "feldspar", "microcline", "orthoclase", "plagioclase",
        "albite", "anorthite", "labradorite", "oligoclase", "andesine",
        "muscovite", "biotite", "phlogopite", "chlorite", "vermiculite",
        "montmorillonite", "smectite", "illite", "kaolinite",
        "halloysite", "talc", "pyrophyllite",
        "serpentine", "antigorite", "lizardite", "chrysotile",
        "pyroxene", "augite", "diopside", "jadeite", "omphacite",
        "enstatite", "hypersthene",
        "hornblende", "actinolite", "tremolite", "amphibole", "glaucophane",
        "olivine", "forsterite", "fayalite",
        "garnet", "almandine", "andradite", "grossular", "pyrope",
        "spessartine", "uvarovite",
        "staurolite", "kyanite", "andalusite", "sillimanite", "cordierite",
        "chloritoid",
        "zircon", "tourmaline", "schorl", "dravite", "elbaite",
        "apatite", "fluorapatite", "monazite", "xenotime",
        "epidote", "zoisite", "clinozoisite", "vesuvianite", "lawsonite",
        "prehnite", "pumpellyite",
        "sodalite", "nepheline", "leucite",
        "titanite", "sphene",
        # Oxides
        "fluorite", "corundum", "diamond", "graphite",
        "hematite", "magnetite", "goethite", "limonite",
        "ilmenite", "rutile", "anatase", "brookite",
        "chromite", "spinel", "cassiterite",
        "wolframite", "scheelite",
        "uraninite", "pitchblende", "thorite",
        # Sulfides
        "pyrite", "marcasite", "chalcopyrite", "sphalerite", "galena",
        "arsenopyrite", "bornite", "covellite", "chalcocite",
        "tetrahedrite", "tennantite", "enargite", "freibergite",
        "bismuthinite", "molybdenite", "cinnabar", "realgar", "orpiment",
        "stibnite", "pentlandite", "pyrrhotite", "cobaltite", "niccolite",
        "millerite", "violarite", "linnaeite",
        # Sulfates / carbonates / halides
        "cerussite", "anglesite", "wulfenite", "vanadinite",
        "barite", "celestite", "gypsum", "anhydrite",
        "halite", "sylvite", "carnallite",
        "malachite", "azurite", "chrysocolla", "smithsonite", "hemimorphite",
        "rhodochrosite", "siderite", "ankerite", "dolomite", "calcite",
        "aragonite", "witherite", "strontianite", "magnesite",
        # Phosphates / arsenates
        "vivianite", "erythrite",
    },

    "lithology": {
        # Igneous — felsic
        "granite", "granitoid", "granodiorite", "tonalite", "trondhjemite",
        "diorite", "monzonite", "syenite", "rhyolite", "dacite", "andesite",
        "trachyte", "phonolite",
        # Igneous — mafic / ultramafic
        "gabbro", "anorthosite", "norite", "peridotite", "dunite",
        "harzburgite", "lherzolite", "pyroxenite", "komatiite",
        "basalt", "diabase", "dolerite",
        # Igneous — alkaline / special
        "carbonatite", "kimberlite", "lamproite", "lamprophyre",
        "pegmatite",
        # Volcanic-textured
        "ignimbrite", "tuff", "breccia", "agglomerate",
        # Sedimentary
        "conglomerate", "sandstone", "arkose", "greywacke", "siltstone",
        "mudstone", "shale", "claystone", "marl",
        "chert", "limestone", "dolostone", "chalk", "coal", "ironstone",
        "bif", "banded iron formation",
        "phosphorite", "evaporite",
        # Metamorphic
        "quartzite", "slate", "phyllite", "schist", "gneiss", "migmatite",
        "marble", "soapstone", "amphibolite", "eclogite", "blueschist",
        "granulite", "charnockite", "skarn", "hornfels",
        "mylonite", "cataclasite", "ultramylonite",
        "greisen",
    },

    "deposit_type": {
        "porphyry", "epithermal", "mesothermal", "hypothermal",
        "iocg", "iron oxide copper gold",
        "vms", "volcanogenic massive sulfide", "volcanic massive sulfide",
        "sedex", "sediment-hosted", "mvt", "mississippi valley type",
        "carlin", "carlin-type",
        "orogenic gold", "orogenic", "intrusion-related",
        "irgs",
        "skarn", "manto", "stratabound", "stratiform",
        "kimberlite", "lateritic", "supergene", "placer", "paleoplacer",
        "bif", "vein", "stockwork", "disseminated", "massive sulfide",
        "breccia pipe", "magmatic sulfide",
        "ree deposit", "alkaline complex",
    },

    "jurisdiction": {
        # Countries
        "chile", "peru", "bolivia", "argentina", "brazil", "colombia",
        "venezuela", "ecuador", "mexico", "guatemala", "honduras",
        "united states", "usa", "canada", "australia", "new zealand",
        "china", "russia", "mongolia", "kazakhstan", "uzbekistan",
        "indonesia", "philippines", "papua new guinea", "japan",
        "south korea", "north korea", "vietnam", "myanmar", "india",
        "iran", "turkey", "saudi arabia",
        "south africa", "democratic republic of congo", "drc",
        "zambia", "namibia", "ghana", "mali", "burkina faso", "tanzania",
        "ethiopia", "egypt", "morocco", "algeria",
        "sweden", "finland", "norway", "spain", "portugal", "ireland",
        "united kingdom", "germany", "france", "italy", "poland",
        "ukraine", "serbia", "romania", "bulgaria",
        "antarctica", "greenland",
        # US states (mining-relevant)
        "nevada", "alaska", "arizona", "california", "idaho", "montana",
        "colorado", "utah", "new mexico", "wyoming", "michigan",
        "minnesota", "wisconsin", "south dakota",
        # Canadian provinces / territories
        "ontario", "quebec", "british columbia", "alberta", "manitoba",
        "saskatchewan", "yukon", "nunavut", "newfoundland", "labrador",
        # Aus states
        "western australia", "queensland", "new south wales", "victoria",
        "northern territory", "south australia", "tasmania",
        # Regions / cratons
        "andes", "cordillera", "rocky mountains", "appalachians",
        "urals", "scandinavian shield", "fennoscandian shield",
        "abitibi", "abitibi greenstone belt",
        "superior craton", "slave craton", "wyoming craton",
        "yilgarn craton", "pilbara craton", "kaapvaal craton",
        "zimbabwe craton", "amazonian craton", "sao francisco craton",
        "north china craton", "siberian craton",
        "tibet", "tibetan plateau", "himalayas",
        "lithos", "cordilleran", "kalahari",
    },

    "element": {
        # Single-letter and two-letter element symbols (periodic table)
        "h", "he", "li", "be", "b", "c", "n", "o", "f", "ne",
        "na", "mg", "al", "si", "p", "s", "cl", "ar", "k", "ca",
        "sc", "ti", "v", "cr", "mn", "fe", "co", "ni", "cu", "zn",
        "ga", "ge", "as", "se", "br", "kr", "rb", "sr", "y", "zr",
        "nb", "mo", "tc", "ru", "rh", "pd", "ag", "cd", "in", "sn",
        "sb", "te", "i", "xe", "cs", "ba",
        "la", "ce", "pr", "nd", "pm", "sm", "eu", "gd", "tb", "dy",
        "ho", "er", "tm", "yb", "lu",
        "hf", "ta", "w", "re", "os", "ir", "pt", "au", "hg",
        "tl", "pb", "bi", "po", "at", "rn",
        "fr", "ra", "ac", "th", "pa", "u",
        "np", "pu", "am", "cm", "bk", "cf", "es", "fm", "md", "no", "lr",
    },

    "structure": {
        # Faults / shear
        "fault", "normal fault", "reverse fault", "thrust", "thrust fault",
        "strike-slip", "transform", "transtension", "transpression",
        "shear zone", "ductile shear", "brittle shear",
        # Folds / fabrics
        "fold", "anticline", "syncline", "monocline", "isocline",
        "recumbent", "foliation", "lineation", "cleavage", "schistosity",
        "fabric", "joint", "fracture",
        # Intrusive bodies (structural context)
        "vein", "stockwork", "dike", "dyke", "sill", "batholith",
        "pluton", "stock", "laccolith", "lopolith", "cupola",
        # Plate tectonic settings
        "subduction", "accretionary wedge", "forearc", "backarc",
        "back-arc", "island arc", "continental arc", "intra-arc",
        "continental rift", "intracontinental rift", "rift", "rifting",
        "mid-ocean ridge", "transform boundary", "spreading center",
        "hotspot", "mantle plume", "plume",
        "lithosphere", "asthenosphere", "mantle",
        # Cratons / orogenic structure
        "craton", "shield", "platform", "terrane", "allochthon", "suture",
        "ophiolite", "suture zone", "collision",
        "orogen", "orogeny", "orogenic belt",
        "fold and thrust belt", "decollement", "foreland basin",
        "back-arc basin", "forearc basin", "rift basin",
    },

    "process": {
        # Alteration
        "metasomatism", "alteration", "propylitic", "phyllic", "argillic",
        "potassic", "sericitic", "sodic", "calc-silicate",
        "advanced argillic", "silicification", "sulfidation",
        "carbonatization",
        # Weathering / surficial
        "weathering", "supergene", "supergene enrichment", "leaching",
        "erosion", "deposition", "sedimentation", "lithification",
        "diagenesis",
        # Metamorphism
        "metamorphism", "regional metamorphism", "contact metamorphism",
        "prograde", "retrograde", "isograd", "metamorphic facies",
        "amphibolite facies", "greenschist facies", "blueschist facies",
        "granulite facies", "eclogite facies",
        # Igneous
        "partial melting", "anatexis", "fractional crystallization",
        "magmatic differentiation", "magmatism", "plutonism", "volcanism",
        "emplacement",
        # Ore-forming
        "hydrothermal", "hydrothermal alteration", "magmatic-hydrothermal",
        "exhalative", "syngenetic", "epigenetic", "mineralization",
        "ore-forming", "ore formation",
        # Fluid
        "fluid inclusion", "fluid flow", "basinal brine", "seawater",
        "meteoric water", "magmatic fluid", "metamorphic fluid",
    },

    "method": {
        # Geochronology / isotopes
        "u-pb", "u/pb", "pb-pb", "re-os", "re/os", "sm-nd", "rb-sr",
        "ar-ar", "k-ar", "lu-hf", "u-th-he", "u-th/he", "fission track",
        "geochronology", "thermochronology",
        # Stable isotopes
        "o-isotope", "δ18o", "delta18o",
        "h-isotope", "δd", "deltad",
        "s-isotope", "δ34s", "delta34s",
        "c-isotope", "δ13c", "delta13c",
        "n-isotope", "δ15n",
        "b-isotope", "δ11b",
        "sr-isotope", "87sr/86sr",
        "pb-isotope", "lead isotope",
        "nd isotope", "hf isotope", "epsilon",
        # Minerals commonly used as chronometers ARE in `mineral` —
        # the *method* phrase is e.g. "zircon U-Pb", not "zircon" alone.
        # Only purpose-built method names belong here.
        # Geochem methods
        "mc-icp-ms", "icp-ms", "la-icp-ms", "sims", "tims",
        "xrf", "electron microprobe", "microprobe", "epma",
        "edx", "sem", "tem", "raman", "ftir", "mossbauer",
        # Geophysics
        "magnetic", "gravity", "em survey", "induced polarization", "ip",
        "seismic", "ground-penetrating radar", "magnetotelluric",
        # Geochemistry / data
        "geochemistry", "whole-rock geochemistry", "trace element",
        "rare earth element pattern", "ree pattern", "spider diagram",
        "primitive mantle", "chondrite-normalized",
        "vectoring", "lithogeochemistry", "soil geochemistry",
        "stream sediment", "biogeochemistry",
        # Exploration
        "drilling", "diamond drilling", "rc drilling", "core logging",
        "alteration mapping", "structural mapping",
        "fluid inclusion microthermometry",
    },
}


# Human-friendly labels for each category, used in template section headers.
CATEGORY_LABELS: dict[str, str] = {
    "commodity": "Commodities & critical minerals",
    "mineral": "Mineralogy",
    "lithology": "Lithology",
    "deposit_type": "Deposit types",
    "jurisdiction": "Geographic / jurisdictional",
    "element": "Elements",
    "structure": "Structural / tectonic",
    "process": "Geological processes",
    "method": "Methodology / proxies",
    "other": "Other",
}


# Display order for category sections (matches how a geologist would
# typically scan an industrial-context view: what is it → what's it
# in → what type → where → how do we measure it).
CATEGORY_ORDER: list[str] = [
    "commodity", "mineral", "lithology", "deposit_type",
    "structure", "process", "jurisdiction", "method", "element", "other",
]


# Reverse-lookup index built once at import time.
_TERM_TO_CATEGORY: dict[str, str] = {}
for _cat, _terms in CATEGORIES.items():
    for _t in _terms:
        _TERM_TO_CATEGORY[_t.lower()] = _cat


def classify(term: str) -> str:
    """Return the category key for `term`, or 'other' if unclassified.

    Match is case-insensitive on exact whole-string equality. Multi-word
    terms ("rare earth elements") need to be in the category set
    verbatim. Single-token partners — which is what xDD tokenization
    produces — are covered by single-token category entries.
    """
    if not term:
        return "other"
    return _TERM_TO_CATEGORY.get(term.strip().lower(), "other")


def group_by_category(
    rows: Iterable[dict],
    *,
    term_key: str = "word",
) -> dict[str, list[dict]]:
    """Split a list of partner rows by category.

    Returns a dict keyed by category name. Categories with no matching
    rows are simply absent from the output (templates should iterate
    `CATEGORY_ORDER` and skip empties). Input order is preserved within
    each category bucket, so callers' upstream sort survives.
    """
    out: dict[str, list[dict]] = {}
    for row in rows:
        cat = classify(str(row.get(term_key, "")))
        out.setdefault(cat, []).append(row)
    return out


def categories_in_display_order(grouped: dict[str, list[dict]]) -> list[tuple[str, str, list[dict]]]:
    """Yield (category_key, label, rows) tuples for non-empty buckets in
    the canonical display order. Convenience for templates."""
    return [
        (cat, CATEGORY_LABELS.get(cat, cat.title()), grouped[cat])
        for cat in CATEGORY_ORDER
        if cat in grouped and grouped[cat]
    ]
