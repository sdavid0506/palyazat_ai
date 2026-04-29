import chromadb
from langchain_anthropic import ChatAnthropic
from langchain_text_splitters import RecursiveCharacterTextSplitter
from dotenv import load_dotenv
import os
import sys

load_dotenv()

# ChromaDB útvonal: exe mellé, nem temp mappába
if getattr(sys, 'frozen', False):
    _BASE = os.path.dirname(sys.executable)
else:
    _BASE = os.path.dirname(os.path.abspath(__file__))

try:
    chroma_client = chromadb.PersistentClient(path=os.path.join(_BASE, "chroma_db"))
    collection = chroma_client.get_or_create_collection(name="palyazatok")
except Exception as e:
    print(f"⚠️  ChromaDB inicializálás sikertelen: {e}")
    chroma_client = None
    collection = None

# Szöveg daraboló (nagy szövegeket kis darabokra vágja)
splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=50
)

def add_document(text, doc_id, metadata={}):
    """Betesz egy dokumentumot az adatbázisba."""
    if collection is None:
        print("⚠️  ChromaDB nem elérhető, stílusminta kihagyva.")
        return
    chunks = splitter.split_text(text)
    try:
        for i, chunk in enumerate(chunks):
            collection.add(
                documents=[chunk],
                metadatas=[{**metadata, "chunk": i}],
                ids=[f"{doc_id}_chunk_{i}"]
            )
        print(f"✅ Betöltve: {len(chunks)} darab – {doc_id}")
    except Exception as e:
        print(f"⚠️  ChromaDB mentés sikertelen: {e}")

def search(query, n_results=3):
    """Keres a tárolt dokumentumokban."""
    if collection is None:
        return []
    try:
        if collection.count() == 0:
            return []
        results = collection.query(
            query_texts=[query],
            n_results=min(n_results, collection.count())
        )
        docs = results["documents"][0]
        print(f"🔍 Találatok száma: {len(docs)}")
        return docs
    except Exception as e:
        print(f"⚠️  ChromaDB keresés sikertelen: {e}")
        return []

def get_context(query):
    """Összefűzi a találatokat egy kontextussá az AI-nak."""
    docs = search(query)
    context = "\n---\n".join(docs)
    return context


def clear_collection():
    """Törli az összes dokumentumot a kollekcióból (új generálás előtt)."""
    if collection is None:
        return
    try:
        ids = collection.get()["ids"]
        if ids:
            collection.delete(ids=ids)
            print(f"🗑️  ChromaDB törölve: {len(ids)} chunk eltávolítva.")
    except Exception as e:
        print(f"⚠️  ChromaDB törlés sikertelen: {e}")


if __name__ == "__main__":
    print("RAG modul kész.")
    print(f"Adatbázis helye: {os.path.join(_BASE, 'chroma_db')}")
    print(f"Tárolt dokumentumok száma: {collection.count()}")