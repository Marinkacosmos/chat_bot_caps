from langchain_community.document_loaders import PyPDFLoader
import docx
import easyocr
import requests
import re
import json
from pathlib import Path
from pdf2image import convert_from_path
import pandas as pd
import easyocr 
import numpy as np 
from pdf2image import convert_from_path

# ---------- 1. Извлечение текста ----------
def extract_text_pdf(path: str) -> str: 
    pages = PyPDFLoader(path).load() 
    text_parts = [] 
    for page in pages: 
        txt = page.page_content.strip()
        if txt: 
            text_parts.append(txt) 
    return "".join(text_parts).replace("\n", " ")

def extract_text_docx(path: str) -> str:
    doc = docx.Document(path)
    return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())

# OCR fallback for scanned PDF pages

def ocr_pdf(path, lang=None):
    if lang is None:
        lang = ['ru', 'en']

    reader = easyocr.Reader(lang, gpu=False)
    images = convert_from_path(path, dpi=300)

    all_text = []

    for img in images:
        img_array = np.array(img)
        results = reader.readtext(img_array, detail=0)

        if results:
            all_text.append("\n".join(results))

    return "\n\n".join(all_text)



def load_document(path: str) -> str:
    p = Path(path)
    if p.suffix.lower() in ['.pdf']:
        text = extract_text_pdf(path)
        if len(text.strip()) < 50:  # вероятно скан — делаем OCR
            text = ocr_pdf(path)
        return text
    elif p.suffix.lower() in ['.docx', '.doc']:
        return extract_text_docx(path)
    else:
        raise ValueError("Поддерживаются только PDF и DOCX")
    
def split_into_chunks(text: str, chunk_size: int = 3000, overlap: int = 200) -> list[str]:
    chunks = []
    start = 0
    length = len(text)

    while start < length:
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap  

    return chunks


# ---------- 2. Промпт для ChatOllama ----------
PROMPT_TEMPLATE = """
Вы эксперт по ревматологии и генетике. Дана клиническая выписка на русском языке. С учетом текста выписки определите, имеются ли у пациента признаки CAPS (Cryopyrin-Associated Periodic Syndromes) и связанные с ними характеристики.
Найдите и верните строго JSON с полями:
"crp_elevated" - true, false или "unknown" в зависимости от наличия информации о повышенном уровне CRP (С реактивный белок);
"saa_elevated" - true, false или "unknown" в зависимости от наличия информации о повышенном уровне SAA (сывороточный амилоид А); 
"hives" - true, false или "unknown" в зависимости от наличия информации о крапивнице; 
"triggers" - true, false или "unknown" в зависимости от наличия информации о триггерах после которых возникают приступы (например холод, стресс);
"sensorineural_hearing_loss" - true, false или "unknown" в зависимости от наличия информации о нейросенсорной тугоухости;
"aseptic_meningitis" - true, false или "unknown" в зависимости от наличия информации об симптомах асептического менингита;
"skeletal_abnormalities" - true, false или "unknown" в зависимости от наличия информации о скелетных аномалиях (разрастание эпифизов, выступающие лобные бугры и пр);       
"eye_lesions" - true, false или "unknown" в зависимости от наличия информации о поражении глаз (конъюктивит, эртсклеорит, увеит и пр);       
"nlrp3_mutations" - список строк с найденными мутациями в гене NLRP3 (например c.123A>G, p.Ala123Val и chr1:11201C>G) или пустой список, если мутации не упомянуты.

{{
 "crp_elevated": true|false|"unknown",
 "saa_elevated": true|false|"unknown",
 "hives": true|false|"unknown",
 "triggers": true|false|"unknown",
 "sensorineural_hearing_loss": true|false|"unknown",
 "aseptic_meningitis": true|false|"unknown",
 "skeletal_abnormalities": true|false|"unknown",
 "eye_lesions": true|false|"unknown",
 "nlrp3_mutations": ["string", ...] or []
}}

Дайте краткие пояснения только если поле неочевидно, но JSON должен быть единственным выводом.
Текст для анализа:
<<<
{report_text}
>>>
"""


# ---------- 3. Вызов ChatOllama через локальный HTTP API ----------
def call_chatollama(report_text: str, model: str = "gpt-oss") -> dict:
    prompt = PROMPT_TEMPLATE.format(report_text=report_text)

    url = "http://localhost:11434/api/chat"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False
    }

    resp = requests.post(url, json=payload, timeout=1000)
    resp.raise_for_status()

    data = resp.json()
    content = data.get("message", {}).get("content", "")

    try:
        return json.loads(content)
    except Exception:
        m = re.search(r"\{.*\}", content, flags=re.S)
        if m:
            return json.loads(m.group(0))
        raise ValueError("Не удалось распарсить JSON:\n" + content)


# ---------- 4. Дополнительный поиск мутаций NLRP3 с помощью regex ----------
MUTATION_PATTERNS = [
    r"c\.\d+[ACGT]{1,100}>[ACGT]{1,100}",          # нуклеотидные замены c.123A>G
    r"p\.[A-Za-z]{1,3}\d+[A-Za-z]{1,3}",  # белковые p.Ala123Val или p.A123V
    r"g\.247[45][0-9]{5}[ACGT]{1,100}>[ACGT]{1,100}",  # геномные мутации g.2474***C>G
    r"chr1:247[45][0-9]{5}[ACGT]{1,100}>[ACGT]{1,100}"  # геномные мутации chr1:2475***C>G
]

def find_nlrp3_mutations(text: str) -> list:
    found = set()
    for pat in MUTATION_PATTERNS:
        for m in re.findall(pat, text, flags=re.IGNORECASE):
            found.add(m.strip())
    return list(found)


# ---------- ClinVar загрузка ----------
def load_clinvar_table(path=".\\db\\db_clinvar_eddited.xlsx"):
    df = pd.read_excel(path)
    df.columns = df.columns.str.strip().str.lower()
    return df


# ---------- Нормализация номенклатуры ----------
def normalize_variant_name(raw):
    if raw is None:
        return None

    s = str(raw).strip()
    # Убираем HGVS префиксы
    s = re.sub(r"(c\.|g\.|p\.|m\.|n\.|chr1:)", '', s, flags=re.IGNORECASE)
    # Убираем скобки
    s = re.sub(r"[() \[\] \s']", "", s)
    # Преобразование аминокислот 3→1 буква
    aa3 = {
        "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D",
        "CYS": "C", "GLN": "Q", "GLU": "E", "GLY": "G",
        "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K",
        "MET": "M", "PHE": "F", "PRO": "P", "SER": "S",
        "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V"
    }

    def convert_aa(match):
        aa_from = match.group(1).upper()
        pos = match.group(2)
        aa_to = match.group(3).upper()
        return f"{aa3.get(aa_from, aa_from)}{pos}{aa3.get(aa_to, aa_to)}"

    # Val34Ala → V34A
    s = re.sub(r'([A-Za-z]{3})(\d+)([A-Za-z]{3})', convert_aa, s)
    return s.upper()

# ---------- Добавляем в JSON ----------
def enrich_mutations_with_clinvar(mutation_list, df_clinvar):
    enriched = []
    # Преобразуем весь ClinVar в строковый вид для поиска 
    df_str = df_clinvar.astype(str)
    if not isinstance(mutation_list, list): 
        mutation_list = [mutation_list]
    for m in mutation_list:
        norm = normalize_variant_name(m)
        found_classifications = set()
        found_name = set()
        # Поиск по всем ячейкам датафрейма 
        for _, row in df_str.iterrows(): 
            row_text = " ".join(row.values).upper() 
            if norm in row_text: 
                # Берём классификацию из оригинального df 
                cls = row.get("germline_classification", "unknown") 
                nam = row.get("name", "unknown") 
                found_classifications.add(cls) 
                found_name.add(nam)
        if not found_classifications: 
            found_classifications = {"unknown"}
            found_name = {"unknown"}
        enriched.append({
            "variant": norm,
            "classification": list(found_classifications),
            "name": list(found_name)
        })
    return enriched

# ---------- 5. Основной рабочий поток ----------
def analyze_report(path: str, progress_callback=None):
    text = load_document(path)
    # 1. Разбиваем текст на чанки
    chunks = split_into_chunks(text, chunk_size=3000, overlap=200)
    total_chunks = len(chunks)
    # 2. Пустой итоговый результат
    final = {
        "crp_elevated": "unknown",
        "saa_elevated": "unknown",
        "hives": "unknown",
        "triggers": "unknown",
        "sensorineural_hearing_loss": "unknown",
        "aseptic_meningitis": "unknown",
        "skeletal_abnormalities": "unknown",
        "eye_lesions": "unknown",
        "nlrp3_mutations": []
    }

    # 3. Обрабатываем каждый чанк
    for i, chunk in enumerate(chunks, start=1):
        if progress_callback: progress_callback(i, total_chunks)
        partial = call_chatollama(chunk, model="gpt-oss")

        # Логика объединения результатов

        for key in [
            "crp_elevated", "saa_elevated", "hives", "triggers",
            "sensorineural_hearing_loss", "aseptic_meningitis",
            "skeletal_abnormalities", "eye_lesions"
        ]:
            if partial.get(key) in [True, False]:
                final[key] = partial[key]

        # Мутации
        muts = partial.get("nlrp3_mutations", []) or []
        for m in muts:
            if m not in final["nlrp3_mutations"]:
                final["nlrp3_mutations"].append(m)

    #4. Дополнительная валидация/дополнение мутаций
    mutations = final.get("nlrp3_mutations", []) or []
    extra = find_nlrp3_mutations(text)
    for e in extra:
        if e not in mutations:
            mutations.append(e)

    #5. ClinVar enrichment
    df_clinvar = load_clinvar_table()
    # Преобразуем весь ClinVar в строковый вид для поиска 

    final["nlrp3_mutations_detailed"] = enrich_mutations_with_clinvar(
        mutations, df_clinvar
    )


    return final