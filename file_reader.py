import os

def read_pdf(file_path):
    import pypdf
    reader = pypdf.PdfReader(file_path)
    pages = [page.extract_text() or "" for page in reader.pages]
    full_text = "\n".join(pages)
    print(f"✅ PDF beolvasva: {len(reader.pages)} oldal")
    return full_text

def read_word(file_path):
    import docx2txt
    text = docx2txt.process(file_path)
    print(f"✅ Word fájl beolvasva")
    return text

def read_file(file_path):
    if not os.path.exists(file_path):
        print(f"❌ Fájl nem található: {file_path}")
        return None

    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        return read_pdf(file_path)
    elif ext in [".docx", ".doc"]:
        return read_word(file_path)
    else:
        print(f"❌ Nem támogatott fájlformátum: {ext}")
        return None

if __name__ == "__main__":
    print("Fájlbeolvasó modul kész!")
    print("Támogatott formátumok: PDF, Word (.docx)")
