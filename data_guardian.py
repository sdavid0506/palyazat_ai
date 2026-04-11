import re

def extract_protected_data(text):
    """Kiszedi és megvédi a számokat, dátumokat, cégneveket."""
    
    protected = {}
    counter = [0]

    def replace(match, prefix):
        key = f"[[{prefix}_{counter[0]}]]"
        protected[key] = match.group(0)
        counter[0] += 1
        return key

    # Számok és összegek (pl. 5 000 000 Ft, 3.5 millió)
    text = re.sub(
        r'\b\d[\d\s]*(?:Ft|HUF|EUR|USD|millió|milliárd|%)\b',
        lambda m: replace(m, "SZAM"),
        text
    )

    # Dátumok (pl. 2024.01.15, 2024-01-15)
    text = re.sub(
        r'\b\d{4}[-\.]\d{2}[-\.]\d{2}\b',
        lambda m: replace(m, "DATUM"),
        text
    )

    # Évszámok (pl. 2024, 2025)
    text = re.sub(
        r'\b20[0-9]{2}\b',
        lambda m: replace(m, "EV"),
        text
    )

    return text, protected


def restore_protected_data(text, protected):
    """Visszahelyettesíti az eredeti adatokat."""
    for key, value in protected.items():
        text = text.replace(key, value)
    return text


# Teszt
if __name__ == "__main__":
    teszt_szoveg = """
    A projekt költségvetése 5 000 000 Ft, amelyet 2024.03.15-ig 
    kell felhasználni. A támogatás mértéke 85%, 
    a befejezési határidő 2025.12.31.
    """

    print("EREDETI SZÖVEG:")
    print(teszt_szoveg)

    modositott, vedett_adatok = extract_protected_data(teszt_szoveg)
    
    print("\nMÓDOSÍTOTT SZÖVEG (AI ezt kapja):")
    print(modositott)

    print("\nVÉDETT ADATOK:")
    for k, v in vedett_adatok.items():
        print(f"  {k} → {v}")

    visszaallitott = restore_protected_data(modositott, vedett_adatok)
    print("\nVISSZAÁLLÍTOTT SZÖVEG:")
    print(visszaallitott)