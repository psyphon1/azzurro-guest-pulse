"""Fixed topic taxonomy for review classification. Bump TAXONOMY_VERSION whenever keywords change."""
from dataclasses import dataclass

TAXONOMY_VERSION = "3"   # 2: added "safety"; 3: five more languages, safety words, meal words out


@dataclass(frozen=True)
class Topic:
    id: str
    label: str
    keywords: tuple[str, ...]


# Keywords are lower-case words or phrases, matched on word boundaries (a plural/-ed/-ing suffix is
# tolerated). Bare 'walk' and 'door' are deliberately absent: 'walked past your room' and 'going out
# the door' are not location / check-in mentions.
_TOPIC_LIST = [
    Topic("safety", "Safety & pests", (
        "cockroach", "cockroaches", "roach", "roaches", "bed bug", "bed bugs", "bedbug", "bedbugs", "mould",
        "mold", "mouldy", "moldy", "black mould", "black mold", "rat", "rats", "mice", "fire", "fire hazard",
        "fire risk", "caught fire", "electrical", "exposed wires", "exposed wiring", "electric shock", "sparks",
        "theft", "stolen", "robbed", "thief", "thieves", "unsafe", "not safe", "dangerous", "assault",
        "assaulted", "harassed", "harassment",
    )),
    Topic("cleanliness", "Cleanliness", (
        "clean", "unclean", "dirty", "dirt", "filthy", "grubby", "grime", "grimy", "stain", "stained",
        "smell", "smelly", "smelt", "stink", "stinks", "stinky", "odour", "odor", "sewerage", "sewage",
        "hair", "hairs", "mould", "mold", "mouldy", "moldy", "dust", "dusty", "spotless", "hygiene",
        "cockroach", "cockroaches", "roach", "roaches", "bug", "bugs", "bedbug", "bedbugs", "insect",
        "insects", "ants", "mice", "mouse", "rat", "rats", "vermin", "pest", "pests", "sticky",
        "rubbish", "trash", "unwashed", "housekeeping", "cleanliness", "tidy", "messy",
    )),
    Topic("check_in", "Check-in experience", (
        "check in", "check-in", "checkin", "check out", "check-out", "checkout", "robo check in",
        "virtual check in", "self check in", "self-check-in", "robot check in", "door code", "access code",
        "entry code", "pin code", "lockbox", "key", "keys", "key card", "keycard", "waiting to check",
        "waited to check", "waited at check", "waiting at check", "early arrival", "late arrival",
        "luggage storage", "baggage storage", "arrival",
    )),
    Topic("staff", "Staff behaviour", (
        "reception", "receptionist", "receptionists", "staff", "rude", "unhelpful", "helpful",
        "friendly", "unfriendly", "polite", "impolite", "courteous", "welcoming", "unwelcoming", "manager",
        "service", "customer service", "host", "no staff on site", "did not care", "didn't care",
        "didnt care", "don't care", "dont care", "uncaring", "no care", "attentive", "dismissive",
        "ignored", "unprofessional", "lovely team", "the team",
    )),
    Topic("noise", "Noise", (
        "noise", "noisy", "loud", "thin walls", "paper thin", "paper-thin", "street noise", "traffic noise",
        "corridor", "hallway noise", "neighbour", "neighbours", "neighbor", "neighbors", "quiet",
        "peaceful", "party", "parties", "partying", "slam", "slamming", "could hear", "couldn't sleep",
        "could not sleep", "earplugs", "ear plugs", "sirens", "construction", "street",
    )),
    Topic("facilities", "Facilities", (
        "air conditioning", "air conditioner", "air-conditioning", "aircon", "a/c", "heating", "heater",
        "lift", "elevator", "kettle", "cups", "cup", "mugs", "kitchen", "kitchenette", "microwave",
        "wifi", "wi-fi", "internet", "fan", "parking", "car park", "towel", "towels", "no milk", "milk",
        "laundry", "washing machine", "tv", "television", "hot water", "pool", "gym", "tea", "coffee",
        "utensils", "cutlery", "crockery", "equipped", "hairdryer", "hair dryer", "iron", "lounge",
        "lobby",
        # meals, and bathroom amenities/availability (a count of toilets is a facility, a broken one is a room fault)
        # "dinner"/"lunch"/"food" are left out: a free dinner is a perk or an event, not a facility.
        "breakfast", "restroom", "restrooms", "mirror",
        "enough bathroom", "enough bathrooms", "enough toilet", "enough toilets", "enough shower", "enough showers",
    )),
    Topic("location", "Location", (
        "location", "located", "close to", "near to", "nearby", "walk to", "walk from", "walking distance",
        "walkable", "short walk", "minute walk", "minutes walk", "min walk", "mins walk", "station",
        "transport", "transportation", "public transport", "train", "trains", "bus", "buses", "tram",
        "light rail", "metro", "stadium", "allianz", "scg", "moore park", "central", "restaurants",
        "cafes", "shops", "convenient location", "airport", "city",
    )),
    Topic("room_condition", "Room condition", (
        "bed", "beds", "mattress", "pillow", "pillows", "linen", "sheets", "window", "windows",
        "bathroom fittings", "spacious", "roomy", "cozy", "cosy", "tap", "taps", "broken", "run down", "run-down", "rundown",
        "tired", "dated", "worn", "worn out", "old", "peeling", "leak", "leaking", "leaks", "damp",
        "damaged", "cracked", "fridge", "refrigerator", "furniture", "carpet", "curtain", "curtains",
        "comfortable", "uncomfortable", "cramped", "tiny", "small room", "needs repair", "needs updating",
        "renovation", "renovated", "maintenance",
    )),
    Topic("value", "Value for money", (
        "price", "priced", "prices", "pricey", "value", "worth", "expensive", "cheap", "cheaper",
        "budget", "overpriced", "affordable", "money", "cost", "costly", "bargain", "rip off", "rip-off",
        "ripoff",
    )),
]

TOPICS: dict[str, Topic] = {t.id: t for t in _TOPIC_LIST}

# Keywords that name a PROBLEM ("dirty", "noisy", "rude"). Negating one of these ("not dirty") is good
# news. Every other keyword is neutral or praise ("clean", "kettle"): negating it ("not clean",
# "no kettle") is bad news. Keep in sync with the keyword lists above.
# Safety words. All of them name a problem, and a safety tag is only ever a complaint (see insights.classify).
SAFETY_KEYWORDS = frozenset(_TOPIC_LIST[0].keywords)

# Phrases removed before matching, so "fire exit" is not a fire and "stole the show" is not a theft.
SAFE_PHRASES = (
    "fire exit", "fire exits", "fire escape", "fire alarm", "fire alarms", "fire door", "fire doors",
    "fire place", "fire extinguisher", "fire extinguishers", "fire drill", "on fire", "stole the show",
    "electrical adaptor", "electrical adapter", "electrical outlet", "electrical outlets", "electrical socket",
    "electrical sockets",
)

# Keywords that only count in the "disliked" box: "I liked the window opened" is not praise for the room.
COMPLAINT_ONLY = frozenset({"window", "windows"})

PROBLEM_KEYWORDS = SAFETY_KEYWORDS | frozenset({
    "unclean", "dirty", "dirt", "filthy", "grubby", "grime", "grimy", "stain", "stained", "smell", "smelly",
    "smelt", "stink", "stinks", "stinky", "odour", "odor", "sewerage", "sewage", "hair", "hairs", "mould",
    "mold", "mouldy", "moldy", "dust", "dusty", "cockroach", "cockroaches", "roach", "roaches", "bug",
    "bugs", "bedbug", "bedbugs", "insect", "insects", "ants", "mice", "mouse", "rat", "rats", "vermin",
    "pest", "pests", "sticky", "rubbish", "trash", "unwashed", "messy",
    "noise", "noisy", "loud", "thin walls", "paper thin", "paper-thin", "street noise", "traffic noise",
    "hallway noise", "party", "parties", "partying", "slam", "slamming", "could hear", "couldn't sleep",
    "could not sleep", "sirens", "construction",
    "rude", "unhelpful", "unfriendly", "impolite", "unwelcoming", "dismissive", "ignored", "unprofessional",
    "did not care", "didn't care", "didnt care", "don't care", "dont care", "uncaring", "no care",
    "broken", "run down", "run-down", "rundown", "tired", "dated", "worn", "worn out", "peeling", "leak",
    "leaking", "leaks", "damp", "damaged", "cracked", "uncomfortable", "cramped", "tiny", "needs repair",
    "needs updating",
    "expensive", "pricey", "overpriced", "costly", "rip off", "rip-off", "ripoff",
    "waiting to check", "waited to check", "waited at check", "waiting at check",
})
