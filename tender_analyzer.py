from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from file_reader import read_file
from dotenv import load_dotenv
import os

load_dotenv()

llm = ChatAnthropic(
    model="claude-haiku-4-5",
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

analyzer_prompt = ChatPromptTemplate.from_messages([
    ("system", """Te egy pályázati kiírás elemző szakértő vagy.
    Elemzed a pályázati kiírásokat és listázod a követelményeket.
    
    FONTOS: Válaszod MINDIG pontosan így nézzen ki:
    
    PALYAZAT_NEVE: [a pályázat neve]
    BEADASI_HATARID: [határidő vagy "nem található"]
    MAX_TAMOGATAS: [maximális támogatási összeg vagy "nem található"]
    TAMOGATAS_ARANY: [támogatás százaléka vagy "nem található"]
    
    KOTELEZO_FEJEZETEK:
    - [fejezet 1]
    - [fejezet 2]
    - [fejezet 3]
    
    KOTELEZO_DOKUMENTUMOK:
    - [dokumentum 1]
    - [dokumentum 2]
    
    ERTÉKELESI_SZEMPONTOK:
    - [szempont 1]
    - [szempont 2]
    
    FONTOS_KOVETELMENYEK:
    - [követelmény 1]
    - [követelmény 2]
    
    HIANYZÓ_ADATOK:
    - [adat amit a cégnek kell megadnia 1]
    - [adat amit a cégnek kell megadnia 2]
    """),
    ("human", """
    Elemezd ezt a pályázati kiírást és listázd ki az összes követelményt:
    
    {text}
    """)
])


def analyze_tender(text):
    """Elemzi a pályázati kiírást."""
    
    if not text or len(text) < 50:
        print("⚠️  Túl rövid szöveg az elemzéshez!")
        return None
    
    print("📋 Pályázati kiírás elemzése folyamatban...")
    
    chain = analyzer_prompt | llm
    response = chain.invoke({"text": text[:5000]})
    
    result = parse_tender(response.content)
    return result


def parse_tender(response):
    """Kiszedi a követelményeket."""
    
    tender = {
        "palyazat_neve": "",
        "beadasi_hatarid": "",
        "max_tamogatas": "",
        "tamogatas_arany": "",
        "kotelezo_fejezetek": [],
        "kotelezo_dokumentumok": [],
        "ertékelesi_szempontok": [],
        "fontos_kovetelmenyek": [],
        "hianyzó_adatok": []
    }
    
    current_section = None
    
    for line in response.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        
        # Egyszerű mezők
        if line.startswith("PALYAZAT_NEVE:"):
            tender["palyazat_neve"] = line.split(":", 1)[1].strip()
        elif line.startswith("BEADASI_HATARID:"):
            tender["beadasi_hatarid"] = line.split(":", 1)[1].strip()
        elif line.startswith("MAX_TAMOGATAS:"):
            tender["max_tamogatas"] = line.split(":", 1)[1].strip()
        elif line.startswith("TAMOGATAS_ARANY:"):
            tender["tamogatas_arany"] = line.split(":", 1)[1].strip()
        
        # Lista szekciók
        elif line.startswith("KOTELEZO_FEJEZETEK:"):
            current_section = "kotelezo_fejezetek"
        elif line.startswith("KOTELEZO_DOKUMENTUMOK:"):
            current_section = "kotelezo_dokumentumok"
        elif line.startswith("ERTÉKELESI_SZEMPONTOK:"):
            current_section = "ertékelesi_szempontok"
        elif line.startswith("FONTOS_KOVETELMENYEK:"):
            current_section = "fontos_kovetelmenyek"
        elif line.startswith("HIANYZÓ_ADATOK:"):
            current_section = "hianyzó_adatok"
        
        # Lista elemek
        elif line.startswith("-") and current_section:
            item = line[1:].strip()
            if item:
                tender[current_section].append(item)
    
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