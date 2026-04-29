from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from data_guardian import extract_protected_data, restore_protected_data
from rag_modul import get_context
from dotenv import load_dotenv
import os

load_dotenv()

llm = ChatAnthropic(
    model="claude-sonnet-4-6",
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

prompt_template = ChatPromptTemplate.from_messages([
    ("system", """Te egy profi pályázatíró asszisztens vagy. 
    A feladatod pályázati szövegeket írni magyarul, 
    professzionális és meggyőző stílusban.
    
    Fontos szabályok:
    - A [[SZAM_x]], [[DATUM_x]], [[EV_x]] jelöléseket NE változtasd meg!
    - Ezek védett adatok, pontosan így kell szerepelniük a szövegben.
    - A megadott kontextus alapján igazodj a stílushoz.
    """),
    ("human", """
    Kontextus (korábbi pályázatokból):
    {context}
    
    Feladat: {task}
    
    Adatok: {data}
    """)
])

def write_section(task, data):
    """Megír egy pályázati részt."""
    
    # 1. Adatok védelme
    protected_data, védett = extract_protected_data(data)
    
    # 2. Releváns kontextus lekérése
    context = get_context(task)
    
    # 3. AI megírja a szöveget
    chain = prompt_template | llm
    response = chain.invoke({
        "context": context,
        "task": task,
        "data": protected_data
    })
    
    generated_text = response.content
    
    # 4. Védett adatok visszahelyettesítése
    final_text = restore_protected_data(generated_text, védett)
    
    return final_text


# Teszt
if __name__ == "__main__":
    feladat = "Írj egy bevezető bekezdést egy digitális fejlesztési pályázathoz"
    
    adatok = """
    Cég neve: TechMagyar Kft.
    Projekt költsége: 5 000 000 Ft
    Támogatás: 85%
    Kezdés: 2025.01.01
    """
    
    print("✍️ Pályázati szöveg generálása...\n")
    eredmeny = write_section(feladat, adatok)
    print(eredmeny)