from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from data_guardian import extract_protected_data, restore_protected_data
from rag_modul import get_context, add_document, clear_collection
from file_reader import read_file
from stylist_agent import analyze_and_save, build_style_prompt
from tender_analyzer import analyze_tender, print_tender_summary
from dotenv import load_dotenv
import re
import os

load_dotenv()

_style_cache = {}  # {"hash": ..., "prompt": ...} – stílusminta cache

llm = ChatAnthropic(
    model="claude-haiku-4-5",
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

# --- WRITER ÁGENS ---
writer_prompt = ChatPromptTemplate.from_messages([
    ("system", """Te egy profi magyar pályázatíró vagy.
    Írj meggyőző, professzionális pályázati szövegeket.
    A [[SZAM_x]], [[DATUM_x]], [[EV_x]] jelöléseket NE változtasd meg!
    """),
    ("human", """
    Kontextus korábbi pályázatokból:
    {context}
    
    Stílus követelmények:
    {style}
    
    Pályázati kiírás követelményei:
    {tender_requirements}
    
    Feladat: {task}
    Adatok: {data}
    
    Írj egy részletes, meggyőző szöveget!
    Ha javítási szempontok szerepelnek az adatok között,
    azokat feltétlenül vedd figyelembe és javítsd ki!
    """)
])

# --- REVIEWER ÁGENS ---
reviewer_prompt = ChatPromptTemplate.from_messages([
    ("system", """Te egy szigorú pályázati lektor vagy.
    Pontozd a szöveget 1-100 között.
    
    FONTOS: Válaszod MINDIG így nézzen ki, semmi más:
    PONTSZAM: 75
    VISSZAJELZES: itt írd a visszajelzést
    
    Ne írj semmi mást, csak ezt a két sort!
    """),
    ("human", """
    Értékeld ezt a pályázati szöveget:
    
    {text}
    
    Pályázati kiírás követelményei amiket teljesíteni kell:
    {tender_requirements}
    
    Szempontok:
    - Szakmai meggyőzőerő
    - Magyar nyelvhelyesség
    - Logikai felépítés
    - Pályázati stílus
    - Követelmények teljesítése (a fenti kiírás alapján!)
    """)
])



def parse_reviewer(response):
    """Kiszedi a pontszámot és visszajelzést."""
    text = response.strip()
    score = 0
    feedback = text

    matches = re.findall(r'\b(\d{1,3})\s*(?:/100|pont|%)?', text)
    for match in matches:
        num = int(match)
        if 1 <= num <= 100:
            score = num
            break

    for line in text.split("\n"):
        line = line.strip()
        if any(x in line.upper() for x in ["VISSZAJELZES:", "VISSZAJELZÉS:"]):
            feedback = line.split(":", 1)[1].strip() if ":" in line else line
            break

    return score, feedback


def pre_analyze(tender_text):
    """Pályázati kiírás előzetes elemzése – csak a hiányzó adatok listáját adja vissza, generálás nélkül."""
    if not tender_text or len(tender_text) < 50:
        return []
    tender = analyze_tender(tender_text)
    if tender:
        return tender.get('hianyzó_adatok', [])
    return []


def run(task, data, tender_text=None, style_text=None, max_rounds=2, progress_callback=None):
    """Elindítja a teljes multi-agent folyamatot."""

    def log(msg, pct=None, partial_text=None):
        if progress_callback:
            progress_callback(msg, pct, partial_text)
        else:
            print(msg)

    log("=" * 50, 0)
    log("MULTI-AGENT PÁLYÁZATÍRÓ ELINDULT", 0)
    log("=" * 50, 0)

    # 1. Adatok védelme
    protected_data, vedett = extract_protected_data(data)

    # 2. Stílus elemzése – csak ha új vagy megváltozott stílusminta
    import hashlib
    style_prompt = ""
    if style_text:
        style_hash = hashlib.md5(style_text.encode()).hexdigest()
        if _style_cache.get("hash") != style_hash:
            log("Stílus elemzése...", 10)
            clear_collection()
            style = analyze_and_save(style_text, "stilus_minta")
            _style_cache["hash"] = style_hash
            _style_cache["prompt"] = build_style_prompt(style)
        else:
            log("Stílusminta változatlan, cache-ből betöltve.", 10)
        style_prompt = _style_cache["prompt"]
    else:
        clear_collection()
        _style_cache.clear()
        style_prompt = "Professzionális, formális pályázati stílus."

    context = get_context(task) if style_text else ""

    # 3. Pályázati kiírás elemzése
    tender_requirements = ""
    if tender_text:
        log("Pályázati kiírás elemzése...", 25)
        tender = analyze_tender(tender_text)
        if tender:
            print_tender_summary(tender)
            tender_requirements = f"""
    PÁLYÁZAT: {tender.get('palyazat_neve', '')}
    HATÁRIDŐ: {tender.get('beadasi_hatarid', '')}
    MAX TÁMOGATÁS: {tender.get('max_tamogatas', '')}
    TÁMOGATÁS ARÁNYA: {tender.get('tamogatas_arany', '')}

    KÖTELEZŐ FEJEZETEK: {', '.join(tender.get('kotelezo_fejezetek', []))}
    FONTOS KÖVETELMÉNYEK: {', '.join(tender.get('fontos_kovetelmenyek', []))}
    KÖTELEZŐ DOKUMENTUMOK: {', '.join(tender.get('kotelezo_dokumentumok', []))}
    ÉRTÉKELÉSI SZEMPONTOK: {', '.join(tender.get('ertékelesi_szempontok', []))}
    JOGOSULTSÁGI FELTÉTELEK: {', '.join(tender.get('jogosultsagi_feltetelek', []))}
    HIÁNYZÓ ADATOK: {', '.join(tender.get('hianyzó_adatok', []))}
    """
    else:
        tender_requirements = "Általános pályázati követelmények."

    writer_chain = writer_prompt | llm
    reviewer_chain = reviewer_prompt | llm

    best_text = ""
    best_score = 0
    extra_instructions = ""

    for round_num in range(1, max_rounds + 1):
        pct = 30 + int((round_num - 1) / max_rounds * 60)
        log(f"{round_num}. kör – Szöveg generálása...", pct)

        writer_response = writer_chain.invoke({
            "context": context,
            "style": style_prompt,
            "tender_requirements": tender_requirements,
            "task": task,
            "data": protected_data + extra_instructions
        })
        raw_text = writer_response.content

        if not raw_text or len(raw_text) < 50:
            log("Üres válasz, újrapróbálkozás...", pct)
            continue

        log(f"Szöveg hossza: {len(raw_text)} karakter", pct + 5, raw_text)

        # Reviewer pontozás
        log(f"{round_num}. kör – Lektorálás...", pct + 10)
        reviewer_response = reviewer_chain.invoke({
            "text": raw_text,
            "tender_requirements": tender_requirements
})
        
        

        score, feedback = parse_reviewer(reviewer_response.content)

        log(f"Pontszám: {score}/100 | {feedback}", pct + 15)

        if score > best_score:
            best_score = score
            best_text = raw_text

        if score >= 85:
            log(f"Elfogadva {round_num}. körben! ({score}/100)", 95)
            break
        else:
            log(f"Újraírás szükséges ({score}/100)...", pct + 15)
            extra_instructions = f"""

FONTOS JAVÍTÁSI SZEMPONTOK A {round_num}. KÖR ALAPJÁN:
- Előző pontszám: {score}/100
- Lektor visszajelzése: {feedback}
- Írj egy jobb, részletesebb és meggyőzőbb verziót!
"""

    if not best_text:
        log("Nem sikerült szöveget generálni!", None)
        return "", 0

    # Védett adatok visszahelyettesítése
    final_text = restore_protected_data(best_text, vedett)

    log(f"Kész! Végső pontszám: {best_score}/100", 100)

    return final_text, best_score



# Teszt
if __name__ == "__main__":
    feladat = "Írj bevezető fejezetet egy digitális fejlesztési pályázathoz"

    adatok = """
    Cég: TechMagyar Kft.
    Projekt költsége: 5 000 000 Ft
    Támogatás mértéke: 85%
    Kezdés: 2025.01.01
    Befejezés: 2026.06.30
    Képzésben résztvevők: 150 fő
    """

    tender_szoveg = """
    DIGITÁLIS FEJLESZTÉSI ALAP 2025
    Beadási határidő: 2025.03.31
    Maximális támogatás: 10 000 000 Ft
    Kötelező fejezetek:
    - Projektleírás és célok
    - Megvalósíthatósági tanulmány
    - Költségvetési terv
    - Fenntarthatósági nyilatkozat
    """

    stilus_szoveg = """
    Tisztelt Bíráló Bizottság!
    Vállalatunk ezúton nyújtja be pályázatát a Digitális Alaphoz.
    Elkötelezettek vagyunk a digitális innováció iránt.
    """

    run(feladat, adatok, tender_text=tender_szoveg, style_text=stilus_szoveg)