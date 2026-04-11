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

chroma_client = chromadb.PersistentClient(path=os.path.join(_BASE, "chroma_db"))
collection = chroma_client.get_or_create_collection(name="palyazatok")

# Szöveg daraboló (nagy szövegeket kis darabokra vágja)
splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=50
)

def add_document(text, doc_id, metadata={}):
    """Betesz egy dokumentumot az adatbázisba."""
    chunks = splitter.split_text(text)
    
    for i, chunk in enumerate(chunks):
        collection.add(
            documents=[chunk],
            metadatas=[{**metadata, "chunk": i}],
            ids=[f"{doc_id}_chunk_{i}"]
        )
    
    print(f"✅ Betöltve: {len(chunks)} darab – {doc_id}")

def search(query, n_results=3):
    """Keres a tárolt dokumentumokban."""
    results = collection.query(
        query_texts=[query],
        n_results=n_results
    )
    
    docs = results["documents"][0]
    print(f"🔍 Találatok száma: {len(docs)}")
    return docs

def get_context(query):
    """Összefűzi a találatokat egy kontextussá az AI-nak."""
    docs = search(query)
    context = "\n---\n".join(docs)
    return context


if __name__ == "__main__":
    print("RAG modul kész.")
    print(f"Adatbázis helye: {os.path.join(_BASE, 'chroma_db')}")
    print(f"Tárolt dokumentumok száma: {collection.count()}")