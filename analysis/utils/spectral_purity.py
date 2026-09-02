from typing import Optional

def classify_purity(purity: Optional[float], min_purity: float) -> str:
    if purity is None:
        return "unknown"
    return "pass" if purity >= min_purity else "below_threshold"