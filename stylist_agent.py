from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from rag_modul import add_document
from dotenv import load_dotenv
import os

load_dotenv()

llm = ChatAnthropic(
    model="claude-haiku-4-5",
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

stylist_prompt = ChatPromptTemplate.from_messages([
    ("system", """Te egy stíluselemző szakértő vagy.
    Elemezd a megadott pályázati szöveg stílusjegyeit.
    
    FONTOS: Válaszod MINDIG pontosan így nézzen ki:
    HANGVETEL: [formális/informális/szakmai/bizalmas]
    MONDATHOSSZ: [rövid/közepes/hosszú]
    SZAKMAI_SZAVAK: [alacsony/közepes/magas]
    SZEMELYES: [igen/nem]
    STILUS_LEIRAS: [2-3 mondatos leírás a stílusról]
    MINTAMONDAT: [egy jellemző mondat a szövegből]
    """),
    ("human", """
    Elemezd ennek a pályázati szövegnek a stílusát:
    
    {text}
    """)
])

def analyze_style(text):
    """Elemzi a szöveg stílusát."""
    
    if not text or len(text) < 50:
        print("⚠️  Túl rövid szöveg az elemzéshez!")
        return None
    
    print("🎨 Stíluselemzés folyamatban...")
    
    chain = stylist_prompt | llm
    response = chain.invoke({"text": text[:3000]})  # max 3000 karakter
    
    result = parse_style(response.content)
    return result


def parse_style(response):
    """Kiszedi a stílusjegyeket."""
    style = {
        "hangvetel": "",
        "mondathossz": "",
        "szakmai_szavak": "",
        "szemelyes": "",
        "stilus_leiras": "",
        "mintamondat": ""
    }
    
    for line in response.strip().split("\n"):
        line = line.strip()
        if line.startswith("HANGVETEL:"):
            style["hangvetel"] = line.split(":", 1)[1].strip()
        elif line.startswith("MONDATHOSSZ:"):
            style["mondathossz"] = line.split(":", 1)[1].strip()
        elif line.startswith("SZAKMAI_SZAVAK:"):
            style["szakmai_szavak"] = line.split(":", 1)[1].strip()
        elif line.startswith("SZEMELYES:"):
            style["szemelyes"] = line.split(":", 1)[1].strip()
        elif line.startswith("STILUS_LEIRAS:"):
            style["stilus_leiras"] = line.split(":", 1)[1].strip()
        elif line.startswith("MINTAMONDAT:"):
            style["mintamondat"] = line.split(":", 1)[1].strip()
    
    return style


def build_style_prompt(style):
    """Stílusutasítást épít a Writer ágensnek."""
    
    if not style:
        return ""
    
    prompt = f"""
STÍLUS KÖVETELMÉNYEK (a feltöltött pályázatok alapján):
- Hangvétel: {style['hangvetel']}
- Mondathosszúság: {style['mondathossz']}
- Szakmai szavak használata: {style['szakmai_szavak']}
- Személyes megszólítás: {style['szemelyes']}
- Stílus leírása: {style['stilus_leiras']}
- Mintamondat: {style['mintamondat']}

Kérlek pontosan ezt a stílust kövesd a generált szövegben!
"""
    return prompt


def analyze_and_save(text, doc_id):
    """Elemzi a stílust és elmenti a RAG adatbázisba."""
    
    # Stílus elemzése
    style = analyze_style(text)
    
    if style:
        print("\n📊 STÍLUSJEGYEK:")
        for k, v in style.items():
            if v:
                print(f"   {k}: {v}")
        
        # Elmenti a RAG-ba stílus metaadatokkal
        add_document(text, doc_id, {
            "hangvetel": style["hangvetel"],
            "mondathossz": style["mondathossz"],
            "tipus": "stilus_minta"
        })
        print(f"\n✅ Stílusminta elmentve: {doc_id}")
    
    return style


# Teszt
if __name__ == "__main__":
    teszt_szoveg = """
    Tisztelt Bíráló Bizottság!
    
    A TechMagyar Kft. ezúton nyújtja be pályázatát a Digitális 
    Fejlesztési Alaphoz. Vállalatunk 2015 óta kiemelkedő szerepet 
    tölt be a hazai technológiai innovációban, és elkötelezett 
    a digitális átalakulás előmozdítása iránt.
    
    Projektünk célja 150 munkavállaló digitális kompetenciáinak 
    fejlesztése, amellyel hosszú távon biztosítjuk vállalatunk 
    versenyképességét az egyre digitalizálódó piaci környezetben.
    A program megvalósítási ideje 18 hónap, összköltségvetése 
    5 000 000 Ft, amelynek 85%-a vissza nem térítendő támogatásból 
    finanszírozható.
    """
    
    style = analyze_and_save(teszt_szoveg, "teszt_palyazat_001")
    
    print("\n📝 WRITER UTASÍTÁS:")
    print(build_style_prompt(style))