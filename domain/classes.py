CLASS_NAMES = ("Plastic", "Glass", "Metal", "Paper")
UNKNOWN_CLASS = "Unknown"
FEEDBACK_CLASS_NAMES = CLASS_NAMES + (UNKNOWN_CLASS,)
VALID_CLASSES = set(CLASS_NAMES)

CLASS_IDS = {name: idx for idx, name in enumerate(CLASS_NAMES)}
CLASS_COLORS = {
    "Plastic": "#1E90FF",
    "Glass": "#00CED1",
    "Metal": "#FF8C00",
    "Paper": "#22c55e",
}


def is_supported_class(name: str) -> bool:
    return name in VALID_CLASSES
