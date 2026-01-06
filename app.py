import streamlit as st
import tempfile
import pandas as pd

# Backend functions
from main import analyze_report, enrich_mutations_with_clinvar, load_clinvar_table
df_clinvar = load_clinvar_table()

# Предварительная загрузка параметров классифкации и клин вопросов
CLASSIFICATION_OPTIONS = [
    "Benign/Likely Benign",
    "VUS",
    "Likely risk allele",
    "not provided",
    "Pathogenic/Likely pathogenic",
    "unknown"
]

FIELDS_TO_CHECK = {
    "crp_elevated": "У пациента повышен CRP?",
    "saa_elevated": "У пациента повышен SAA?",
    "hives": "Есть ли упоминание о крапивнице?",
    "triggers": "Есть ли триггеры приступов (холод, стресс)?",
    "sensorineural_hearing_loss": "Есть ли нейросенсорная тугоухость?",
    "aseptic_meningitis": "Есть ли признаки асептического менингита?",
    "skeletal_abnormalities": "Есть ли скелетные аномалии?",
    "eye_lesions": "Есть ли поражения глаз (конъюктивит, увеит и пр)?",
    "nlrp3_mutations": "Есть ли данные о вариантах в гене NLRP3?"
}

#Счетчик chunks при загрузке файлов
if "uploader_key" not in st.session_state: st.session_state.uploader_key = 0

# запуск страницы_лицевой части
st.set_page_config(page_title="CAPS Clinical Report Analyzer", layout="centered")
st.title("🧬 CAPS Clinical Report Analyzer")
st.write(
    "Загрузите PDF или DOCX файл с клиническими и генетическими данными пациента. Я помогу проанализировать симптомы CAPS и "
    "генетические варианты в гене NLRP3.")
st.write("❗Валидировано для транскрипта NM_001243133.2 и геномных сборкок Grch38/hg38 и Grch37/hg19.❗"
)

# -------------------------------
# State initialization
# -------------------------------
if "result" not in st.session_state:
    st.session_state.result = None

if "clarification_index" not in st.session_state:
    st.session_state.clarification_index = 0

if "unknown_fields" not in st.session_state:
    st.session_state.unknown_fields = []

if "edit_mode" not in st.session_state:
    st.session_state.edit_mode = False


# -------------------------------
# Step 1 — File upload
# -------------------------------
uploaded_file = st.file_uploader(
    "📄 Загрузите файл клинического заключения и/или анамнеза (PDF или DOCX)",
    type=["pdf", "docx"],
    key=f"uploader_{st.session_state.uploader_key}"
)

if uploaded_file and st.session_state.result is None:

    with tempfile.NamedTemporaryFile(delete=False, suffix=uploaded_file.name) as tmp:
        tmp.write(uploaded_file.read())
        temp_path = tmp.name

    # Создаём прогресс-бар и текстовое поле
    progress_bar = st.progress(0)
    progress_text = st.empty()

    # Вызываем анализ с передачей callback-функции
    result = analyze_report(
        temp_path,
        progress_callback=lambda i, total: (
            progress_bar.progress(int((i / total) * 100)),
            progress_text.write(f"Обрабатывается сегмент {i} из {total}")
        )
    )


    st.session_state.result = result

    unknowns = []
    for key, value in result.items():
        if key in FIELDS_TO_CHECK:
            if value in ["unknown", "", None] or (isinstance(value, list) and len(value) == 0):
                unknowns.append(key)

    st.session_state.unknown_fields = unknowns
    st.session_state.clarification_index = 0
    st.session_state.edit_mode = False


# -------------------------------
# Step 2 — Clarification loop
# -------------------------------
if st.session_state.result is not None:

    if st.session_state.clarification_index < len(st.session_state.unknown_fields):
        st.write(
            "Автоматическая аннотация медицинского заключения с использованием ИИ не "
            "смогла собрать все необходимые данные для консультации по CAPS синдрому. "
            "Не могли бы Вы уточнить следующие детали:"
        )
        current_field = st.session_state.unknown_fields[st.session_state.clarification_index]
        question = FIELDS_TO_CHECK[current_field]

        st.info(f"❓ {question}")

        # --- ОСОБЫЙ СЛУЧАЙ ДЛЯ NLRP3 ---
        if current_field == "nlrp3_mutations":
            col_yes, col_no = st.columns(2)

            with col_yes:
                yes_clicked = st.button("✅ Да", key=f"yes_btn_{current_field}")
            with col_no:
                no_clicked = st.button("❌ Нет", key=f"no_btn_{current_field}")

            
            if no_clicked:
                st.session_state.result[current_field] = []
                st.session_state.clarification_index += 1
                st.rerun()

            
            if yes_clicked:
                st.session_state.result[current_field] = []  # просто помечаем, что мутации есть
                st.session_state.nlrp3_manual_input = True
                st.rerun()

            # Если мы на шаге ручного ввода мутаций
            if st.session_state.get("nlrp3_manual_input", False):
                variant = st.text_input(
                    "Введите нуклеотидный вариант (например: c.1322C>T)",
                    key="manual_variant_input"
                )

                submit_variant = st.button("➡️ Подтвердить вариант")

                if submit_variant and variant.strip():
                    # Сохраняем мутацию
                    st.session_state.result["nlrp3_mutations"] = [v.strip() for v in variant.split(",") if v.strip()]

                    # Обогащаем ClinVar
                    st.session_state.result["nlrp3_mutations_detailed"] = enrich_mutations_with_clinvar(
                        st.session_state.result["nlrp3_mutations"],
                        df_clinvar
                    )

                    # очищаем флаг
                    st.session_state.nlrp3_manual_input = False
                    st.session_state.clarification_index += 1
                    st.rerun()

                # пока не нажали "Подтвердить" — останавливаем выполнение
                st.stop()

            # пока ни "Да", ни "Нет" не нажали — просто ждём
            st.stop()

        # --- ОБЫЧНЫЕ ПОЛЯ ---
        col_yes, col_no = st.columns(2)

        with col_yes:
            yes_clicked = st.button("✅ Да", key=f"yes_btn_{current_field}")
        with col_no:
            no_clicked = st.button("❌ Нет", key=f"no_btn_{current_field}")

        if yes_clicked:
            st.session_state.result[current_field] = True
            st.session_state.clarification_index += 1
            st.rerun()

        if no_clicked:
            st.session_state.result[current_field] = False
            st.session_state.clarification_index += 1
            st.rerun()


    else:
        # -------------------------------
        # Step 3 — Final review
        # -------------------------------
        st.success("Все поля уточнены! Проверьте итоговые значения:")

        result = st.session_state.result

        # Build editable structure (WITHOUT detailed mutations)
        rows = []

        for key, value in result.items():

            if key == "nlrp3_mutations":
                # Convert list → single string
                if isinstance(value, list):
                    text_value = ", ".join(value) if isinstance(value, list) else str(value)
                else:
                    text_value = str(value)

                rows.append({"field": key, "value": text_value, "type": "mutations"})

            elif key != "nlrp3_mutations_detailed":
                rows.append({"field": key, "value": value, "type": "bool"})
        
        df_display = pd.DataFrame(rows)

        # Show detailed mutations separately
        

        detailed = result.get("nlrp3_mutations_detailed", [])
        detailed_rows = []

        for item in detailed:
            variant = item.get("variant", "")
            classification_list = item.get("classification", [])
            name_list = item.get("name", [])
            classification = classification_list[0] if classification_list else "Unknown"
            name = name_list[0] if name_list else "Unknown"
            detailed_rows.append({
                "variant": variant,
                "classification": classification,
                "Name": name
            })
           
        df_detailed = pd.DataFrame(detailed_rows)
        

        # -------------------------------
        # Edit mode
        # -------------------------------
        if not st.session_state.edit_mode:
            st.subheader("🩺 Данные клинического анализа")
            st.table(df_display)
            st.divider() 
            st.subheader("🧬 Детализированные варианты NLRP3") 
            st.table(df_detailed)
            col1, col2 = st.columns(2)
            with col1:
                confirm = st.button("✅ Да, всё верно")
            with col2:
                edit = st.button("✏️ Необходимы изменения")

            if confirm:
                result = st.session_state.result

                # -------------------------------
                # 1. Собираем данные
                # -------------------------------
                crp = result.get("crp_elevated") is True
                saa = result.get("saa_elevated") is True

                inflammatory_marker = crp or saa

                # Симптомы для правил 1–2
                symptom_list_1 = [
                    result.get("hives") is True,
                    result.get("triggers") is True,
                    result.get("sensorineural_hearing_loss") is True,
                    result.get("aseptic_meningitis") is True,
                    result.get("skeletal_abnormalities") is True
                ]
                symptom_count_1 = sum(symptom_list_1)

                # Симптомы для правил 3–4
                symptom_list_2 = [
                    result.get("hives") is True,
                    result.get("sensorineural_hearing_loss") is True,
                    result.get("eye_lesions") is True  
                ]
                symptom_count_2 = sum(symptom_list_2)

                # Мутации
                mutations = result.get("nlrp3_mutations", [])
                detailed = result.get("nlrp3_mutations_detailed", [])

                has_mutation_info = len(mutations) > 0

                # -------------------------------
                # 2. Проверяем detailed классификацию
                # -------------------------------
                detailed_classes = [item.get("classification", [""])[0] for item in detailed]

                has_pathogenic = any(cls == "Pathogenic/Likely pathogenic" for cls in detailed_classes)

                has_vus = any(cls == "VUS" for cls in detailed_classes)

                # -------------------------------
                # 3. Формируем вывод
                # -------------------------------
                final_message = ""

                # --- Правило 3 ---
                if (has_pathogenic and symptom_count_2 >= 1) or (has_vus and symptom_count_2 >= 2):
                    final_message = (
                        "Исходя из клинических показателей и молекулярно-генетических данных "
                        "можно поставить диагноз CAPS."
                    )
                elif (detailed_classes == "unknown" and symptom_count_2 >= 1) or (has_mutation_info and symptom_count_2 >= 2):
                    final_message = (
                        "Точная постановка диагноза CAPS невозможна.\n\n "
                        "Рекомендуется повторный биоинформатический и функциональный анализ результатов молекулярно-генетичкского "
                        "исследования, а также продолжение клинического наблюдения пациента. "
                        "При назначении врача возможно повторное проведение молекулярно-генетического исследования гена NLRP3.\n\n "
                        "Подробнее: https://nczd.ru/price/laboratornaja-diagnostika/genetic/#:~:text=17.027.250" 
                    
                    )

                # --- Правило 1 ---
                elif inflammatory_marker and symptom_count_1 >= 2 and not has_mutation_info:
                    final_message = (
                        "Необходимо проведение молекулярно-генетического исследования гена NLRP3 в экстренном порядке! "
                        "У пациента присутствует как повышение С-реактивного белка и/или сывороточного "
                        "амилоидного белка А, так и "
                        f"{symptom_count_1} подкрепляющих диагностических признака.\n\n"
                        "Подробнее: https://nczd.ru/price/laboratornaja-diagnostika/genetic/#:~:text=17.027.250"
                    )

                # --- Правило 2 ---
                elif (inflammatory_marker and symptom_count_1 < 2 and not has_mutation_info) or (not inflammatory_marker and not has_mutation_info):
                    final_message = (
                        "Исходя из клинических данных не определена необходимость проведения "
                        "молекулярно-генетического исследования гена NLRP3 в экстренном порядке. "
        
                    )
                
                # -------------------------------
                # 4. Вывод результата
                # -------------------------------
                if final_message:
                    st.subheader("📌 Заключение")
                    st.write(final_message)
                else:
                    st.subheader("📌 Заключение")
                    st.write("Недостаточно данных для формирования заключения.")

                st.stop()


            if edit:
                st.session_state.edit_mode = True
                st.rerun()
       
        # -------------------------------
        # Step 3.5 — Edit mode
        # -------------------------------
       
        else:
            st.info("Измените значения и нажмите «Сохранить изменения».")

            edited = {}

            for row in rows:

                if row["type"] == "bool":
                    edited[row["field"]] = st.selectbox(
                        row["field"],
                        [True, False],
                        index=0 if row["value"] is True else 1,
                        key=f"edit_{row['field']}"
                    )

                elif row["type"] == "mutations":
                    edited_text = st.text_input(
                        row["field"],
                        value=row["value"],
                        key=f"edit_{row['field']}"
                    )
                    edited[row["field"]] = [v.strip() for v in edited_text.split(",") if v.strip()]

            # Detailed mutations editing
            st.subheader("Самостоятельное указание патогенности генетических вариантов в гене NLRP3")

            edited_detailed = []
            for idx, item in enumerate(detailed_rows):
                st.write(f"Вариант: **{item['variant']}** (read‑only)")

                current_class = item["classification"]

                if current_class not in CLASSIFICATION_OPTIONS:
                    st.caption(f"Текущее значение: {current_class} (read‑only)")
                    default_index = 0
                else:
                    default_index = CLASSIFICATION_OPTIONS.index(current_class)

                new_class = st.selectbox(
                    f"Классификация для {item['variant']}",
                    CLASSIFICATION_OPTIONS,
                    index=default_index,
                    key=f"class_det_{idx}"
                )

                edited_detailed.append({
                    "variant": item["variant"],
                    "classification": [new_class]
                })

            save = st.button("💾 Сохранить изменения")

            if save:
                new_json = {}

                # Rebuild JSON
                for key, value in edited.items():
                    if key == "nlrp3_mutations":
                        new_json["nlrp3_mutations"] = value
                    else:
                        new_json[key] = value

                new_json["nlrp3_mutations_detailed"] = edited_detailed

                # Compare mutations
                old_mut = result.get("nlrp3_mutations")
                new_mut = new_json.get("nlrp3_mutations")

                if old_mut != new_mut:
                    new_json["nlrp3_mutations_detailed"] = enrich_mutations_with_clinvar(new_json["nlrp3_mutations"], df_clinvar)

                st.session_state.result = new_json
                st.session_state.edit_mode = False
                st.success("Изменения сохранены.")
                st.rerun()


# -------------------------------
# Restart button (always visible)
# -------------------------------

st.markdown("---")
if st.button("🔄 Начать заново"):
    st.session_state.clear()
    st.session_state.uploader_key = st.session_state.get("uploader_key", 0) + 1
    st.rerun()
