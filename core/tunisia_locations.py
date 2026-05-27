"""
All 24 Tunisian governorates and their delegations.
Source: Institut National de la Statistique (INS) Tunisia.
"""

TUNISIA_LOCATIONS: dict[str, list[str]] = {
    "Tunis": [
        "Tunis Ville", "Centre Ville", "Bab Bhar", "Bab Souika",
        "El Omrane", "El Omrane Supérieur", "El Menzah", "Cité El Khadra",
        "Le Bardo", "Séjoumi", "Ezzouhour", "Hrairia", "Sidi Hassine",
        "El Ouardia", "Jebel Jelloud",
        "La Marsa", "Carthage", "La Goulette", "Le Kram",
        "Les Berges du Lac", "Lac 1", "Lac 2", "Les Jardins de Carthage",
        "Cité Olympique", "Mutuelleville", "El Manar", "Ain Zaghouan",
        "Cité Ettahrir",
    ],
    "Ariana": [
        "Ariana Ville", "Soukra", "Raoued", "Kalâat el-Andalous",
        "Sidi Thabet", "Ettadhamen", "Mnihla",
    ],
    "Ben Arous": [
        "Ben Arous", "Nouvelle Médina", "Mourouj", "Hammam Lif", "Hammam Chott",
        "Bou Mhel el-Bassatine", "Ezzahra", "Radès", "Mégrine", "Mohamedia",
        "Fouchana", "Mornag",
    ],
    "Manouba": [
        "Manouba", "Den Den", "Douar Hicher", "Oued Ellil", "Tébourba",
        "El Batan", "Jedaïda", "Mornaguia", "Borj El Amri", "Djedeida",
    ],
    "Nabeul": [
        "Nabeul", "Dar Chaabane El Fehri", "Beni Khiar", "Korba", "Menzel Temime",
        "Kélibia", "El Haouaria", "Takelsa", "Soliman", "Menzel Bouzelfa",
        "Grombalia", "Bou Argoub", "Hammamet", "Béni Khalled",
    ],
    "Zaghouan": [
        "Zaghouan", "Zriba", "Djebel Oust", "El Fahs", "Nadhour", "Saouaf",
    ],
    "Bizerte": [
        "Bizerte Nord", "Bizerte Sud", "Zarzouna", "Séjenane", "Joumine",
        "Ghézala", "El Alia", "Utique", "Ghar El Melah", "Menzel Bourguiba",
        "Tinja", "Menzel Jemil", "Mateur", "Ghedir", "Raoued",
    ],
    "Béja": [
        "Béja Nord", "Béja Sud", "Amdoun", "Nefza", "Téboursouk",
        "Testour", "Goubellat", "Medjez El Bab",
    ],
    "Jendouba": [
        "Jendouba", "Jendouba Nord", "Bou Salem", "Tabarka", "Aïn Draham",
        "Fernana", "Ghardimaou", "Oued Meliz", "Balta Bou Aouane",
    ],
    "Kef": [
        "Kef Ouest", "Kef Est", "Nebeur", "Sakiet Sidi Youssef", "Tajerouine",
        "Kalâat Senan", "Kalâat Khasba", "Jerissa", "El Ksour", "Dahmani", "Sers",
    ],
    "Siliana": [
        "Siliana Nord", "Siliana Sud", "Bou Arada", "Gaâfour", "El Krib",
        "Sidi Bou Rouis", "Makthar", "Rouhia", "Kesra", "Bargou",
    ],
    "Sousse": [
        "Sousse Médina", "Sousse Riadh", "Sousse Jawhara", "Sousse Sidi Abdelhamid",
        "Hammam Sousse", "Akouda", "Kalâa Kebira", "Sidi Bou Ali",
        "Hergla", "Enfidha", "Bouficha", "Kondar", "Sidi El Heni",
        "M'Saken", "Kalâa Seghira",
    ],
    "Monastir": [
        "Monastir", "Kondar", "Sahline", "Zeramdine", "Beni Hassen",
        "Jammel", "Bembla", "Moknine", "Bokri", "Ouerdanine",
        "Sayada-Lamta-Bou Hajar", "Téboulba", "Ksar Hellal",
        "Ksibet el-Médiouni",
    ],
    "Mahdia": [
        "Mahdia", "Bou Merdes", "Ouled Chamekh", "Chorbane", "Hébira",
        "Souassi", "Bir Ali Ben Khalifa", "Sidi Alouane", "Ksour Essef",
        "El Bradaa", "Melloulèche",
    ],
    "Sfax": [
        "Sfax Ville", "Sfax Ouest", "Sfax Sud", "Sakiet Eddaïer", "Sakiet Ezzit",
        "Chihia", "Agareb", "Djebeniana", "El Amra", "El Hencha",
        "Menzel Chaker", "Ghraïba", "Bir Ali Ben Khalifa", "Skhira",
        "Mahres", "Kerkennah",
    ],
    "Kairouan": [
        "Kairouan Nord", "Kairouan Sud", "El Ouesslatia", "Chébika",
        "Sbikha", "El Alâa", "Hajeb El Aïoun", "Nasrallah",
        "El Cherarda", "Bouhajla",
    ],
    "Kasserine": [
        "Kasserine Nord", "Kasserine Sud", "Ezzouhour", "Hassi El Ferid",
        "Majel Bel Abbès", "Hidra", "Foussana", "Feriana",
        "Thélepte", "Sbeitla", "Djedeliane", "El Ayoun",
    ],
    "Sidi Bouzid": [
        "Sidi Bouzid Ouest", "Sidi Bouzid Est", "Jilma", "Cebala",
        "Meknassy", "Souk Jedid", "Mezzouna", "Regueb",
        "Ouled Haffouz", "Bir El Hafey", "Sidi Ali Ben Aoun",
        "Menzel Bouzaïane",
    ],
    "Gabès": [
        "Gabès Médina", "Gabès Ouest", "Gabès Sud", "Ghannouch",
        "El Hamma", "El Metouia", "Ouedhref", "Nouvelle Matmata",
        "Matmata", "Mareth", "Menzel El Habib",
    ],
    "Medenine": [
        "Medenine Nord", "Medenine Sud", "Ben Gardane", "Zarzis",
        "Jerba Houmt Souk", "Jerba Midoun", "Jerba Ajim", "Sidi Makhlouf",
        "Beni Khedache",
    ],
    "Tataouine": [
        "Tataouine Nord", "Tataouine Sud", "Bir Lahmar", "Ghomrassen",
        "Smar", "Remada", "El Ksar",
    ],
    "Gafsa": [
        "Gafsa Nord", "Gafsa Sud", "Sidi Aïch", "El Ksar",
        "Moularès", "Redeyef", "Métlaoui", "Mdhila",
        "El Guettar", "Belkhir", "Sened",
    ],
    "Tozeur": [
        "Tozeur", "Degache", "Tameghza", "Nefta", "Hazoua",
    ],
    "Kebili": [
        "Kebili Nord", "Kebili Sud", "Souk Lahad", "Douz Nord",
        "Douz Sud", "Faouar",
    ],
}

# Flat sorted list of all governorates
GOVERNORATES: list[str] = sorted(TUNISIA_LOCATIONS.keys())


def get_delegations(governorate: str) -> list[str]:
    """Return delegations for a governorate, sorted alphabetically."""
    return sorted(TUNISIA_LOCATIONS.get(governorate, []))


def search_location(query: str) -> list[tuple[str, str]]:
    """
    Search for a governorate or delegation by partial name.
    Returns list of (governorate, delegation) tuples.
    An empty delegation string means the match is at governorate level.
    """
    query = query.strip().lower()
    if not query:
        return []

    matches: list[tuple[str, str]] = []
    for gov, delegations in TUNISIA_LOCATIONS.items():
        if query in gov.lower():
            matches.append((gov, ""))
        for deleg in delegations:
            if query in deleg.lower():
                matches.append((gov, deleg))

    return matches
