from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from file_reader import read_file
from dotenv import load_dotenv
import hashlib
import os

load_dotenv()

llm = ChatAnthropic(
    model="claude-sonnet-4-6",
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

_tender_cache = {}  # {"hash": ..., "result": ...}


def clear_tender_cache():
    """Törli a tender elemzés cache-t (pl. fájl eltávolításakor)."""
    _tender_cache.clear()

analyzer_prompt = ChatPromptTemplate.from_messages([
    ("system", """Te egy tapasztalt magyar pályázati elemző szakértő vagy.
Feladatod: bármilyen típusú pályázati kiírást vagy támogatási felhívást elemezni —
legyen az klasszikus fejezetes pályázat VAGY modern támogatási konstrukció (pl. KTH, GINOP, turisztikai felhívás).

ELEMZÉSI SZABÁLYOK:
- Olvasd végig a TELJES szöveget mielőtt válaszolsz
- Minden konkrét számot, határidőt, feltételt pontosan másold ki
- Ha egy adat nem szerepel a szövegben, írd: "nem található"
- NE találj ki adatokat, NE általánosíts — csak ami a szövegben van
- A HIANYZÓ_ADATOK szekcióba CSAK olyan kérdések kerüljenek,
  amiket a CÉGNEK kell megválaszolnia (nem a pályázatból kiderülő infók!)

FONTOS: Válaszod MINDIG pontosan így nézzen ki, semmi más szöveg:

PALYAZAT_NEVE: [teljes hivatalos név és azonosítószám]
BEADASI_HATARID: [pontos dátum, vagy nyitott ha "forrás kimerüléséig"]
MAX_TAMOGATAS: [pontos összeg Ft-ban]
TAMOGATAS_ARANY: [százalék]
MEGVALOSITAS_HATARIDEJE: [projekt fizikai befejezés határideje]
FENNTARTASI_KOTELEZETTSEG: [fenntartási időszak hossza]

JOGOSULTSAGI_FELTETELEK:
- [minden számszerű jogosultsági küszöb, pl. "Minimális nettó árbevétel: 12 000 000 Ft/év"]
- [regisztrációs követelmények, pl. "NTAK regisztráció kötelező"]
- [aktivitási feltételek, pl. "2025-ben minimum 210 nyitvatartott nap"]
- [szervezeti forma feltételek]
- [kizáró körülmények]

KOTELEZO_DOKUMENTUMOK:
- [minden kötelező melléklet sorszámmal és pontos névvel]

TAMOGATHATO_TEVEKENYSEGEK:
- [minden támogatható tevékenységkategória]

NEM_TAMOGATHATO_KOLTSEGEK:
- [explicit kizárt költségek]

FONTOS_HATARIDOK:
- [minden határidő típusa és pontos dátuma]

HIANYZÓ_ADATOK:
- [csak olyan kérdés ami a CÉG specifikus adatára kérdez rá, pl. "Van-e aktív NTAK regisztrációjuk?"]
- [pl. "Az elmúlt 12 hónap nettó árbevétele?"]
- [pl. "Kaptak-e de minimis támogatást az elmúlt 3 évben? Ha igen, mennyi volt?"]
- [pl. "Az ingatlan saját tulajdon vagy bérelt?"]
"""),
    ("human", """
Elemezd ezt a pályázati kiírást és töltsd ki PONTOSAN a megadott sablont.
Minden mezőt tölts ki, minden feltételt, dokumentumot és határidőt nyerj ki a szövegből!

{text}
""")
])


CHUNK_SIZE = 10000


def _split_by_paragraphs(text, max_size=CHUNK_SIZE):
    """Bekezdéshatáron vágja a szöveget – egy bekezdés sosem kerül két chunkba."""
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    chunks = []
    current = ""
    for para in paragraphs:
        if current and len(current) + len(para) + 2 > max_size:
            chunks.append(current.strip())
            current = para
        else:
            current = (current + "\n\n" + para) if current else para
    if current.strip():
        chunks.append(current.strip())
    return chunks


def analyze_tender(text):
    """Elemzi a pályázati kiírást – nagy fájlokat bekezdéshatáron darabolja.
    Cache-eli az eredményt, így ugyanazt a fájlt csak egyszer elemzi."""

    if not text or len(text) < 50:
        print("⚠️  Túl rövid szöveg az elemzéshez!")
        return None

    text_hash = hashlib.md5(text.encode()).hexdigest()
    if _tender_cache.get("hash") == text_hash:
        print("📋 Pályázati kiírás cache-ből betöltve.")
        return _tender_cache["result"]

    chunks = _split_by_paragraphs(text)
    print(f"📋 Pályázati kiírás elemzése: {len(chunks)} rész...")

    chain = analyzer_prompt | llm
    results = []
    for i, chunk in enumerate(chunks):
        print(f"   {i + 1}/{len(chunks)}. rész elemzése...")
        response = chain.invoke({"text": chunk})
        result = parse_tender(response.content)
        if result:
            results.append(result)

    if not results:
        return None

    final = results[0] if len(results) == 1 else _merge_tender_results(results)
    _tender_cache["hash"] = text_hash
    _tender_cache["result"] = final
    return final


def _merge_tender_results(results):
    """Több részből kapott elemzési eredményeket összefésüli."""
    merged = {
        "palyazat_neve": "",
        "beadasi_hatarid": "",
        "max_tamogatas": "",
        "tamogatas_arany": "",
        "megvalositas_hatarideje": "",
        "fenntartasi_kotelezettseg": "",
        "kotelezo_fejezetek": [],
        "kotelezo_dokumentumok": [],
        "ertékelesi_szempontok": [],
        "fontos_kovetelmenyek": [],
        "jogosultsagi_feltetelek": [],
        "tamogathato_tevekenysegek": [],
        "nem_tamogathato_koltsegek": [],
        "fontos_hataridok": [],
        "hianyzó_adatok": []
    }

    # String mezők: első nem-üres, nem "nem található" érték
    for field in ["palyazat_neve", "beadasi_hatarid", "max_tamogatas",
                  "tamogatas_arany", "megvalositas_hatarideje", "fenntartasi_kotelezettseg"]:
        for r in results:
            val = r.get(field, "").strip()
            if val and "nem tal" not in val.lower():
                merged[field] = val
                break

    # Lista mezők: egyedi elemek összegyűjtése az összes részből
    for field in ["kotelezo_fejezetek", "kotelezo_dokumentumok", "ertékelesi_szempontok",
                  "fontos_kovetelmenyek", "jogosultsagi_feltetelek", "tamogathato_tevekenysegek",
                  "nem_tamogathato_koltsegek", "fontos_hataridok", "hianyzó_adatok"]:
        seen = set()
        for r in results:
            for item in r.get(field, []):
                key = item.lower().strip()
                if key not in seen:
                    seen.add(key)
                    merged[field].append(item)
        merged[field] = _dedup_substrings(merged[field])

    # Visszafelé kompatibilitás
    if not merged["fontos_kovetelmenyek"] and merged["jogosultsagi_feltetelek"]:
        merged["fontos_kovetelmenyek"] = merged["jogosultsagi_feltetelek"]

    print(f"✅ Összefésülve: {len(results)} részből")
    return merged


def _dedup_substrings(items):
    """Eltávolítja azokat az elemeket, amelyek egy másik elem részhalmazai.
    A rövidebb/általánosabb változatot dobja el, a hosszabbat/specifikusabbat tartja meg."""
    normalized = [item.lower().strip() for item in items]
    keep = []
    for i, item in enumerate(items):
        a = normalized[i]
        is_sub = any(
            i != j and a in normalized[j]
            for j in range(len(items))
        )
        if not is_sub:
            keep.append(item)
    return keep


def parse_tender(response):
    tender = {
        "palyazat_neve": "",
        "beadasi_hatarid": "",
        "max_tamogatas": "",
        "tamogatas_arany": "",
        "megvalositas_hatarideje": "",
        "fenntartasi_kotelezettseg": "",
        "kotelezo_fejezetek": [],      # visszafelé kompatibilitás miatt marad
        "kotelezo_dokumentumok": [],
        "ertékelesi_szempontok": [],
        "fontos_kovetelmenyek": [],
        "jogosultsagi_feltetelek": [],
        "tamogathato_tevekenysegek": [],
        "nem_tamogathato_koltsegek": [],
        "fontos_hataridok": [],
        "hianyzó_adatok": []
    }

    current_section = None

    for line in response.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        if line.startswith("PALYAZAT_NEVE:"):
            tender["palyazat_neve"] = line.split(":", 1)[1].strip()
        elif line.startswith("BEADASI_HATARID:"):
            tender["beadasi_hatarid"] = line.split(":", 1)[1].strip()
        elif line.startswith("MAX_TAMOGATAS:"):
            tender["max_tamogatas"] = line.split(":", 1)[1].strip()
        elif line.startswith("TAMOGATAS_ARANY:"):
            tender["tamogatas_arany"] = line.split(":", 1)[1].strip()
        elif line.startswith("MEGVALOSITAS_HATARIDEJE:"):
            tender["megvalositas_hatarideje"] = line.split(":", 1)[1].strip()
        elif line.startswith("FENNTARTASI_KOTELEZETTSEG:"):
            tender["fenntartasi_kotelezettseg"] = line.split(":", 1)[1].strip()

        elif line.startswith("JOGOSULTSAGI_FELTETELEK:"):
            current_section = "jogosultsagi_feltetelek"
        elif line.startswith("KOTELEZO_DOKUMENTUMOK:"):
            current_section = "kotelezo_dokumentumok"
        elif line.startswith("TAMOGATHATO_TEVEKENYSEGEK:"):
            current_section = "tamogathato_tevekenysegek"
        elif line.startswith("NEM_TAMOGATHATO_KOLTSEGEK:"):
            current_section = "nem_tamogathato_koltsegek"
        elif line.startswith("FONTOS_HATARIDOK:"):
            current_section = "fontos_hataridok"
        elif line.startswith("HIANYZÓ_ADATOK:"):
            current_section = "hianyzó_adatok"
        elif line.startswith("KOTELEZO_FEJEZETEK:"):
            current_section = "kotelezo_fejezetek"
        elif line.startswith("ERTÉKELESI_SZEMPONTOK:"):
            current_section = "ertékelesi_szempontok"
        elif line.startswith("FONTOS_KOVETELMENYEK:"):
            current_section = "fontos_kovetelmenyek"

        elif line.startswith("-") and current_section:
            item = line[1:].strip()
            if item:
                tender[current_section].append(item)

    # Visszafelé kompatibilitás: fontos_kovetelmenyek = jogosultsagi_feltetelek
    if not tender["fontos_kovetelmenyek"] and tender["jogosultsagi_feltetelek"]:
        tender["fontos_kovetelmenyek"] = tender["jogosultsagi_feltetelek"]


    if tender:
            print("=== TENDER ANALYZER KIMENET ===")
            import json
            print(json.dumps(tender, ensure_ascii=False, indent=2))
            print_tender_summary(tender)

    return tender


def print_tender_summary(tender):
    """Szépen kiírja az elemzés eredményét."""
    
    print("\n" + "=" * 50)
    print("📋 PÁLYÁZATI KIÍRÁS ELEMZÉSE")
    print("=" * 50)
    
    print(f"\n📌 Pályázat neve: {tender['palyazat_neve']}")
    print(f"⏰ Beadási határidő: {tender['beadasi_hatarid']}")
    print(f"💰 Max támogatás: {tender['max_tamogatas']}")
    print(f"📊 Támogatás aránya: {tender['tamogatas_arany']}")
    
    if tender["kotelezo_fejezetek"]:
        print("\n📝 Kötelező fejezetek:")
        for f in tender["kotelezo_fejezetek"]:
            print(f"   ✅ {f}")
    
    if tender["kotelezo_dokumentumok"]:
        print("\n📂 Kötelező dokumentumok:")
        for d in tender["kotelezo_dokumentumok"]:
            print(f"   📄 {d}")
    
    if tender["ertékelesi_szempontok"]:
        print("\n⭐ Értékelési szempontok:")
        for e in tender["ertékelesi_szempontok"]:
            print(f"   🔍 {e}")
    
    if tender["fontos_kovetelmenyek"]:
        print("\n⚠️  Fontos követelmények:")
        for k in tender["fontos_kovetelmenyek"]:
            print(f"   ❗ {k}")
    
    if tender["hianyzó_adatok"]:
        print("\n❓ Ezeket az adatokat kell megadnod:")
        for h in tender["hianyzó_adatok"]:
            print(f"   👉 {h}")
    
    print("\n" + "=" * 50)


def get_required_fields(tender):
    """Visszaadja a kötelező mezőket stringként az Orchestratornak."""
    fields = tender["kotelezo_fejezetek"] + tender["hianyzó_adatok"]
    return ", ".join(fields) if fields else ""


# Teszt
if __name__ == "__main__":
    teszt_kiiras = """
    DIGITÁLIS FEJLESZTÉSI ALAP – PÁLYÁZATI KIÍRÁS 2025
    
    Beadási határidő: 2025.03.31
    Maximális támogatás: 10 000 000 Ft
    Támogatás intenzitása: 85%
    
    Kötelező fejezetek:
    1. Projektleírás és célok
    2. Megvalósíthatósági tanulmány
    3. Költségvetési terv
    4. Fenntarthatósági nyilatkozat
    5. Környezetvédelmi terv
    
    Szükséges dokumentumok:
    - Cégkivonat (30 napnál nem régebbi)
    - Adóigazolás
    - Mérleg és eredménykimutatás
    - Referenciák listája
    
    Értékelési szempontok:
    - Innováció mértéke (30 pont)
    - Gazdasági hatás (25 pont)
    - Megvalósíthatóság (25 pont)
    - Fenntarthatóság (20 pont)
    
    A pályázónak meg kell adnia:
    - Cég teljes neve és adószáma
    - Projekt pontos kezdési és befejezési dátuma
    - Saját forrás mértéke
    - Kapcsolattartó neve és elérhetősége
    """
    
    tender = analyze_tender(teszt_kiiras)
    if tender:
        print_tender_summary(tender)
        print("\n📌 Kötelező mezők az Orchestratornak:")
        print(get_required_fields(tender))