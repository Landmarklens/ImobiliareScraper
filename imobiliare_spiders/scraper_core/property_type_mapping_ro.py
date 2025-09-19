"""
Property type mapping for Romanian real estate
Maps Romanian property types to standardized types
"""

# Romanian to English property type mapping
ROMANIAN_PROPERTY_TYPES = {
    # Apartments
    "apartament": "apartment",
    "apartamente": "apartment",
    "ap": "apartment",
    "garsoniera": "studio",
    "garsoniere": "studio",
    "studio": "studio",

    # Houses
    "casa": "house",
    "case": "house",
    "casă": "house",
    "vila": "villa",
    "vile": "villa",
    "vilă": "villa",
    "duplex": "duplex",
    "triplex": "triplex",
    "casa individuala": "house",
    "casa individuală": "house",
    "casa de vacanta": "vacation_home",
    "casa de vacanță": "vacation_home",

    # Commercial
    "spatiu comercial": "commercial",
    "spațiu comercial": "commercial",
    "spatiu birouri": "office",
    "spațiu birouri": "office",
    "birou": "office",
    "birouri": "office",
    "magazin": "retail",
    "restaurant": "restaurant",
    "hotel": "hotel",
    "pensiune": "guesthouse",

    # Land
    "teren": "land",
    "terenuri": "land",
    "teren constructii": "building_land",
    "teren construcții": "building_land",
    "teren agricol": "agricultural_land",
    "teren intravilan": "urban_land",
    "teren extravilan": "rural_land",

    # Industrial
    "hala": "warehouse",
    "hală": "warehouse",
    "depozit": "warehouse",
    "spatiu industrial": "industrial",
    "spațiu industrial": "industrial",
    "fabrica": "factory",
    "fabrică": "factory",

    # Other residential
    "penthouse": "penthouse",
    "mansarda": "attic",
    "mansardă": "attic",
    "camin": "dormitory",
    "cămin": "dormitory",
    "camera": "room",
    "cameră": "room",

    # Farm/Rural
    "ferma": "farm",
    "fermă": "farm",
    "cabana": "cabin",
    "cabană": "cabin",
    "conac": "manor",
}

# Standardized property types (output)
STANDARD_PROPERTY_TYPES = {
    "apartment",
    "studio",
    "house",
    "villa",
    "duplex",
    "triplex",
    "penthouse",
    "room",
    "commercial",
    "office",
    "retail",
    "restaurant",
    "hotel",
    "guesthouse",
    "warehouse",
    "industrial",
    "factory",
    "land",
    "building_land",
    "agricultural_land",
    "urban_land",
    "rural_land",
    "vacation_home",
    "farm",
    "cabin",
    "manor",
    "attic",
    "dormitory",
}


def standardize_property_type(property_type_text: str) -> str:
    """
    Convert Romanian property type to standardized English type

    Args:
        property_type_text: Romanian property type text

    Returns:
        Standardized property type string
    """
    if not property_type_text:
        return "apartment"  # Default

    # Clean and normalize input
    cleaned = property_type_text.lower().strip()

    # Remove common suffixes/prefixes
    cleaned = cleaned.replace("de vanzare", "").replace("de vânzare", "")
    cleaned = cleaned.replace("de inchiriat", "").replace("de închiriat", "")
    cleaned = cleaned.replace("pentru", "").strip()

    # Direct mapping
    if cleaned in ROMANIAN_PROPERTY_TYPES:
        return ROMANIAN_PROPERTY_TYPES[cleaned]

    # Partial matching - check if any key is contained in the text
    for romanian_type, english_type in ROMANIAN_PROPERTY_TYPES.items():
        if romanian_type in cleaned:
            return english_type

    # Check for standard English types already
    for standard_type in STANDARD_PROPERTY_TYPES:
        if standard_type in cleaned:
            return standard_type

    # Special cases based on keywords
    if any(word in cleaned for word in ["ap.", "apart", "bloc"]):
        return "apartment"
    elif any(word in cleaned for word in ["gars", "studio"]):
        return "studio"
    elif any(word in cleaned for word in ["casa", "casă", "house"]):
        return "house"
    elif any(word in cleaned for word in ["vila", "vilă", "villa"]):
        return "villa"
    elif any(word in cleaned for word in ["teren", "lot", "land"]):
        return "land"
    elif any(word in cleaned for word in ["birou", "office", "birouri"]):
        return "office"
    elif any(word in cleaned for word in ["comercial", "commercial", "magazin", "shop"]):
        return "commercial"

    # Default fallback
    return "apartment"


def get_deal_type_from_url(url: str) -> str:
    """
    Determine deal type (rent/buy) from URL

    Args:
        url: Property URL

    Returns:
        'rent' or 'buy'
    """
    if not url:
        return "rent"

    url_lower = url.lower()

    # Romanian terms for rent
    rent_terms = ["inchiri", "închiri", "chirie", "rent"]
    for term in rent_terms:
        if term in url_lower:
            return "rent"

    # Romanian terms for buy
    buy_terms = ["vanzare", "vânzare", "vand", "vând", "cumpar", "cumpăr", "sale", "buy"]
    for term in buy_terms:
        if term in url_lower:
            return "buy"

    # Default to rent if unclear
    return "rent"