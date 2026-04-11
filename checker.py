"""
checker.py
----------
A generált pályázati szöveg és az ellenőrzőlista összevetése AI segítségével.
Visszaadja hogy melyik követelmény teljesült és melyik nem.
"""

from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv
import os
import json

load_dotenv()

llm = ChatAnthropic(
    model="claude-haiku-4-5",
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

checker_prompt = ChatPromptTemplate.from_messages([
    ("system", """Te egy pályázati szöveg ellenőrző vagy.
Megvizsgálod hogy a pályázati szöveg teljesíti-e a megadott követelményeket.

FONTOS: Válaszod MINDIG érvényes JSON legyen, semmi más:
{{"teljesitett": ["követelmény1", "követelmény2"], "hianyzik": ["követelmény3"]}}

Légy megértő – ha a szöveg lényegében teljesít egy követelményt (más szóval is),
azt tekintsd teljesítettnek.
"""),
    ("human", """Vizsgáld meg ezt a pályázati szöveget:

{szoveg}

---
Teljesíti-e az alábbi követelményeket? (add vissza JSON-ban)

Követelmények:
{kovetelmenyek}
""")
])


def check_requirements(szoveg: str, kovetelmenyek: list) -> dict:
    """
    Megvizsgálja hogy a szöveg teljesíti-e a követelményeket.

    Visszatér:
        {"teljesitett": [...], "hianyzik": [...]}
    """
    if not szoveg or not kovetelmenyek:
        return {"teljesitett": [], "hianyzik": kovetelmenyek}

    kov_str = "\n".join(f"- {k}" for k in kovetelmenyek)

    chain = checker_prompt | llm
    response = chain.invoke({
        "szoveg": szoveg[:6000],
        "kovetelmenyek": kov_str
    })

    try:
        raw = response.content.strip()
        # JSON blokk kinyerése ha van markdown körülötte
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        # Biztonság: ha valami hiányzik a válaszból
        if "teljesitett" not in result:
            result["teljesitett"] = []
        if "hianyzik" not in result:
            result["hianyzik"] = kovetelmenyek
        return result
    except Exception:
        # Ha nem sikerül parse-olni, visszaadjuk hogy minden hiányzik
        return {"teljesitett": [], "hianyzik": kovetelmenyek}
