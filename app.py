import streamlit as st
import random
import base64
from translations import t
from db import (
    init_db, get_or_create_google_user, record_answer, get_question_stats,
    create_session, update_session_score, get_user_sessions,
    get_session_wrong_answers,
    get_user_profile, update_user_profile,
    toggle_favorite, get_favorite_tests,
    get_all_tests, get_test, get_test_questions, get_test_questions_by_ids,
    get_test_tags, rename_test_tag, delete_test_tag, create_test, update_test, delete_test,
    add_question, update_question, delete_question, get_next_question_num,
    get_test_materials, add_test_material, delete_test_material,
    create_program, update_program, delete_program, get_program,
    get_all_programs, add_test_to_program, remove_test_from_program,
    get_program_tests, get_program_questions, get_program_tags,
)

init_db()


def _is_logged_in():
    """Return True if user is authenticated."""
    return bool(st.session_state.get("user_id"))


def _try_login():
    """Attempt to log in the user silently, supporting both st.user and st.experimental_user."""
    if st.session_state.get("user_id"):
        return

    user_info = getattr(st, "user", getattr(st, "experimental_user", None))

    if user_info and hasattr(user_info, "is_logged_in"):
        try:
            if user_info.is_logged_in:
                email = user_info.email
                name = getattr(user_info, "name", email) or email

                user_id = get_or_create_google_user(email, name)
                st.session_state.user_id = user_id
                st.session_state.username = name
        except Exception as e:
            st.warning(t("auth_not_configured", e=e))


def _difficulty_score(q, question_stats):
    """Return a score that prioritizes questions the user gets wrong more often."""
    stats = question_stats.get(q["id"])
    if stats is None:
        return 0.5
    total = stats["correct"] + stats["wrong"]
    if total == 0:
        return 0.5
    return stats["wrong"] / total


def select_balanced_questions(questions, selected_tags, num_questions, question_stats=None):
    """Select questions balanced across selected tags, prioritizing difficult ones."""
    filtered = [q for q in questions if q["tag"] in selected_tags]

    if not filtered:
        return []

    if num_questions >= len(filtered):
        random.shuffle(filtered)
        return filtered

    questions_by_tag = {}
    for q in filtered:
        tag = q["tag"]
        if tag not in questions_by_tag:
            questions_by_tag[tag] = []
        questions_by_tag[tag].append(q)

    for tag in questions_by_tag:
        if question_stats:
            questions_by_tag[tag].sort(
                key=lambda q: _difficulty_score(q, question_stats),
                reverse=True,
            )
        else:
            random.shuffle(questions_by_tag[tag])

    selected = []
    tag_list = list(questions_by_tag.keys())
    tag_index = 0

    while len(selected) < num_questions:
        tag = tag_list[tag_index % len(tag_list)]
        if questions_by_tag[tag]:
            selected.append(questions_by_tag[tag].pop(0))
        else:
            tag_list.remove(tag)
            if not tag_list:
                break
        tag_index += 1

    random.shuffle(selected)
    return selected


def shuffle_question_options(questions):
    """Shuffle options for each question, updating answer_index accordingly."""
    for q in questions:
        correct_option = q["options"][q["answer_index"]]
        shuffled = list(q["options"])
        random.shuffle(shuffled)
        q["options"] = shuffled
        q["answer_index"] = shuffled.index(correct_option)
    return questions


def reset_quiz():
    """Reset quiz state."""
    for key in ["quiz_started", "questions", "current_index", "answered",
                "score", "show_result", "selected_answer", "wrong_questions",
                "round_history", "current_round", "current_test_id",
                "current_session_id", "session_score_saved", "active_quiz_level"]:
        if key in st.session_state:
            del st.session_state[key]


LANGUAGE_OPTIONS = ["", "es", "en", "fr", "ca", "de", "pt", "it"]
LANGUAGE_KEYS = {"": "", "es": "lang_es", "en": "lang_en", "fr": "lang_fr", "ca": "lang_ca", "de": "lang_de", "pt": "lang_pt", "it": "lang_it"}
LANGUAGE_FLAGS = {"es": "🇪🇸", "en": "🇬🇧", "fr": "🇫🇷", "ca": "🇦🇩", "de": "🇩🇪", "pt": "🇵🇹", "it": "🇮🇹"}
UI_LANGUAGES = ["es", "en", "fr", "ca"]
UI_LANG_LABELS = {"es": "🇪🇸 ES", "en": "🇬🇧 EN", "fr": "🇫🇷 FR", "ca": "🇦🇩 CA"}


def _lang_display(code):
    """Return display label for a language code."""
    if not code:
        return ""
    flag = LANGUAGE_FLAGS.get(code, "")
    name = t(LANGUAGE_KEYS.get(code, ""), ) if code in LANGUAGE_KEYS else code
    return f"{flag} {name}".strip()


def _render_test_card(test, favorites, prefix=""):
    """Render a single test card with heart and select button."""
    test_id = test["id"]
    is_fav = test_id in favorites
    logged_in = _is_logged_in()

    with st.container(border=True):
        if logged_in:
            col_fav, col_info, col_btn = st.columns([0.5, 4, 1])
            with col_fav:
                heart = "❤️" if is_fav else "🤍"
                if st.button(heart, key=f"{prefix}fav_{test_id}"):
                    toggle_favorite(st.session_state.user_id, test_id)
                    st.rerun()
        else:
            col_info, col_btn = st.columns([4, 1])
        with col_info:
            st.subheader(test["title"])
            if test.get("description"):
                st.write(test["description"])
            meta = t("n_questions", n=test['question_count'])
            if test.get("author"):
                meta += f"  ·  {t('author', name=test['author'])}"
            if test.get("language"):
                meta += f"  ·  {_lang_display(test['language'])}"
            st.caption(meta)
        with col_btn:
            if st.button(t("select"), key=f"{prefix}select_{test_id}", use_container_width=True):
                st.session_state.selected_test = test_id
                st.session_state.page = "Configurar Test"
                st.rerun()


def show_test_catalog():
    """Show a searchable catalog of available tests."""
    user_id = st.session_state.get("user_id")
    all_tests = get_all_tests(user_id)

    if not all_tests:
        st.error(t("no_tests"))
        return

    st.header(t("available_tests"))

    col_search, col_lang = st.columns([3, 1])
    with col_search:
        search = st.text_input(t("search_test"), placeholder=t("search_placeholder"), key="test_search")
    with col_lang:
        # Build language filter options from available tests
        available_langs = sorted({tt["language"] for tt in all_tests if tt.get("language")})
        lang_options = [""] + available_langs
        lang_labels = {code: _lang_display(code) if code else t("all_languages") for code in lang_options}
        selected_lang = st.selectbox(
            t("language"), options=lang_options,
            format_func=lambda x: lang_labels[x],
            key="test_lang_filter",
        )

    logged_in = _is_logged_in()
    favorites = get_favorite_tests(st.session_state.user_id) if logged_in else set()

    if logged_in:
        if st.button(t("create_test"), type="secondary"):
            st.session_state.page = "Crear Test"
            st.rerun()

    filtered_tests = [
        tt for tt in all_tests
        if (not search or search.lower() in tt["title"].lower())
        and (not selected_lang or tt.get("language") == selected_lang)
    ]

    if not filtered_tests:
        st.info(t("no_tests_found"))
        return

    fav_tests = [tt for tt in filtered_tests if tt["id"] in favorites]
    other_tests = [tt for tt in filtered_tests if tt["id"] not in favorites]

    if fav_tests:
        st.subheader(t("favorites"))
        for test in fav_tests:
            _render_test_card(test, favorites, prefix="fav_")

    if other_tests:
        if fav_tests:
            st.subheader(t("all_tests"))
        for test in other_tests:
            _render_test_card(test, favorites)


def show_test_config():
    """Show configuration for the selected test before starting."""
    test_id = st.session_state.get("selected_test")
    if not test_id:
        st.session_state.page = "Tests"
        st.rerun()
        return

    test = get_test(test_id)
    if not test:
        st.error(t("test_not_found"))
        return

    questions = get_test_questions(test_id)
    tags = get_test_tags(test_id)

    st.header(test["title"])
    if test.get("description"):
        st.write(test["description"])
    caption_parts = []
    if test.get("author"):
        caption_parts.append(t("author", name=test['author']))
    if test.get("language"):
        caption_parts.append(_lang_display(test['language']))
    if caption_parts:
        st.caption("  ·  ".join(caption_parts))

    # Show materials if any
    materials = get_test_materials(test_id)
    if materials:
        with st.expander(t("reference_materials", n=len(materials))):
            for mat in materials:
                type_icons = {"pdf": "📄", "youtube": "▶️", "image": "🖼️", "url": "🔗"}
                icon = type_icons.get(mat["material_type"], "📎")
                label = mat["title"] or mat["url"] or t("no_title")
                if mat["material_type"] in ("youtube", "url") and mat["url"]:
                    st.markdown(f"{icon} [{label}]({mat['url']})")
                elif mat["material_type"] == "image" and mat["file_data"]:
                    st.write(f"{icon} {label}")
                    st.image(mat["file_data"], width=300)
                elif mat["material_type"] == "pdf" and mat["file_data"]:
                    st.download_button(
                        f"{icon} {label}",
                        data=mat["file_data"],
                        file_name=f"{label}.pdf",
                        key=f"config_dl_mat_{mat['id']}",
                    )
                else:
                    st.write(f"{icon} {label}")

    col_back, col_edit = st.columns([1, 1])
    with col_back:
        if st.button(t("back_to_tests")):
            del st.session_state.selected_test
            st.session_state.page = "Tests"
            st.rerun()
    with col_edit:
        if _is_logged_in() and test["owner_id"] == st.session_state.user_id:
            if st.button(t("edit_test")):
                st.session_state.editing_test_id = test_id
                st.session_state.page = "Editar Test"
                st.rerun()

    st.subheader(t("configuration"))

    if not questions:
        st.info(t("no_questions"))
        return

    num_questions = st.number_input(
        t("num_questions"),
        min_value=1,
        max_value=len(questions),
        value=min(25, len(questions))
    )

    level_options = ["easy", "difficult"]
    level_labels = {"easy": t("level_easy"), "difficult": t("level_difficult")}
    quiz_level = st.selectbox(
        t("level"),
        options=level_options,
        format_func=lambda x: level_labels[x],
        key="quiz_level",
    )

    st.write(t("topics_to_include"))
    selected_tags = []
    cols = st.columns(2)
    for i, tag in enumerate(tags):
        tag_display = tag.replace("_", " ").title()
        if cols[i % 2].checkbox(tag_display, value=True, key=f"tag_{tag}"):
            selected_tags.append(tag)

    if not selected_tags:
        st.warning(t("select_at_least_one_topic"))
    else:
        filtered_count = len([q for q in questions if q["tag"] in selected_tags])
        st.info(t("available_questions_with_topics", n=filtered_count))

        if st.button(t("start_test"), type="primary"):
            logged_in = _is_logged_in()
            stats = get_question_stats(st.session_state.user_id, test_id) if logged_in else None
            quiz_questions = select_balanced_questions(
                questions, selected_tags, num_questions, stats
            )
            session_id = None
            if logged_in:
                session_id = create_session(
                    st.session_state.user_id, test_id,
                    0, len(quiz_questions),
                )
            st.session_state.questions = shuffle_question_options(quiz_questions)
            st.session_state.current_index = 0
            st.session_state.score = 0
            st.session_state.answered = False
            st.session_state.show_result = False
            st.session_state.selected_answer = None
            st.session_state.wrong_questions = []
            st.session_state.round_history = []
            st.session_state.current_round = 1
            st.session_state.current_test_id = test_id
            st.session_state.current_session_id = session_id
            st.session_state.active_quiz_level = quiz_level
            st.session_state.quiz_started = True
            st.session_state.page = "Tests"
            st.rerun()


def show_quiz():
    """Show the active quiz flow."""
    questions = st.session_state.questions
    current_index = st.session_state.current_index

    if current_index >= len(questions):
        current_round = st.session_state.get("current_round", 1)
        score = st.session_state.score
        total = len(questions)
        wrong = st.session_state.get("wrong_questions", [])

        # Update session score in DB
        session_id = st.session_state.get("current_session_id")
        if _is_logged_in() and session_id and not st.session_state.get("session_score_saved"):
            update_session_score(session_id, score, total)
            st.session_state.session_score_saved = True

        # Save current round to history if not already saved
        history = st.session_state.get("round_history", [])
        if len(history) < current_round:
            history.append({
                "round": current_round,
                "score": score,
                "total": total,
                "wrong": list(wrong),
            })
            st.session_state.round_history = history

        st.header(t("round_completed"))

        # Current round result
        percentage = (score / total) * 100
        st.subheader(t("round_n", n=current_round))
        st.metric(t("score_label"), f"{score}/{total} ({percentage:.1f}%)")

        if percentage >= 80:
            st.success(t("excellent"))
        elif percentage >= 60:
            st.info(t("good_job"))
        else:
            st.warning(t("keep_practicing"))

        # Accumulated summary across all rounds
        if len(history) > 1:
            st.divider()
            st.subheader(t("accumulated_summary"))
            total_all = sum(r["total"] for r in history)
            correct_all = sum(r["score"] for r in history)
            pct_all = (correct_all / total_all) * 100
            st.metric(t("accumulated_total"), f"{correct_all}/{total_all} ({pct_all:.1f}%)")

            for r in history:
                r_pct = (r["score"] / r["total"]) * 100
                icon = "✓" if r_pct == 100 else "○"
                st.write(f"{icon} **{t('round_n', n=r['round'])}:** {r['score']}/{r['total']} ({r_pct:.1f}%)")

        # Show wrong questions from current round
        if wrong:
            st.divider()
            st.subheader(t("wrong_questions_round", n=len(wrong)))
            for i, q in enumerate(wrong, 1):
                tag_display = q["tag"].replace("_", " ").title()
                with st.expander(f"{i}. {q['question']}"):
                    st.caption(t("topic", name=tag_display))
                    correct = q["options"][q["answer_index"]]
                    st.success(t("correct_answer", answer=correct))
                    st.info(t("explanation", text=q['explanation']))

            col1, col2 = st.columns(2)
            with col1:
                if st.button(t("retry_wrong"), type="primary"):
                    next_round = current_round + 1
                    random.shuffle(wrong)
                    new_session_id = None
                    if _is_logged_in():
                        new_session_id = create_session(
                            st.session_state.user_id,
                            st.session_state.current_test_id,
                            0, len(wrong),
                        )
                    st.session_state.questions = shuffle_question_options(wrong)
                    st.session_state.current_index = 0
                    st.session_state.score = 0
                    st.session_state.answered = False
                    st.session_state.selected_answer = None
                    st.session_state.wrong_questions = []
                    st.session_state.current_round = next_round
                    st.session_state.current_session_id = new_session_id
                    st.session_state.session_score_saved = False
                    st.rerun()
            with col2:
                if st.button(t("back_to_start")):
                    reset_quiz()
                    st.rerun()
        else:
            if st.button(t("back_to_start")):
                reset_quiz()
                st.rerun()
        return

    question = questions[current_index]

    col1, col2 = st.columns([3, 1])
    with col1:
        st.progress((current_index) / len(questions))
    with col2:
        st.write(t("question_n_of", current=current_index + 1, total=len(questions)))

    st.subheader(question["question"])

    tag_display = question["tag"].replace("_", " ").title()
    st.caption(t("topic", name=tag_display))

    is_difficult = st.session_state.get("active_quiz_level") == "difficult"

    if not st.session_state.answered:
        if is_difficult:
            user_text = st.text_input(t("your_answer"), key=f"open_answer_{current_index}")
            if st.button(t("submit_answer"), type="primary", key=f"submit_{current_index}"):
                correct_text = question["options"][question["answer_index"]]
                is_correct = user_text.strip().lower() == correct_text.strip().lower()
                st.session_state.selected_answer = user_text.strip()
                st.session_state.answered = True
                if is_correct:
                    st.session_state.score += 1
                else:
                    st.session_state.wrong_questions.append(question)
                if _is_logged_in():
                    record_answer(
                        st.session_state.user_id,
                        st.session_state.current_test_id,
                        question["id"],
                        is_correct,
                        st.session_state.get("current_session_id"),
                    )
                st.rerun()
        else:
            for i, option in enumerate(question["options"]):
                if st.button(option, key=f"option_{i}", use_container_width=True):
                    st.session_state.selected_answer = i
                    st.session_state.answered = True
                    is_correct = i == question["answer_index"]
                    if is_correct:
                        st.session_state.score += 1
                    else:
                        st.session_state.wrong_questions.append(question)
                    if _is_logged_in():
                        record_answer(
                            st.session_state.user_id,
                            st.session_state.current_test_id,
                            question["id"],
                            is_correct,
                            st.session_state.get("current_session_id"),
                        )
                    st.rerun()

    else:
        correct_index = question["answer_index"]
        correct_text = question["options"][correct_index]

        if is_difficult:
            user_text = st.session_state.selected_answer
            is_correct = user_text.lower() == correct_text.strip().lower()
            if is_correct:
                st.success(t("correct"))
            else:
                st.error(t("incorrect"))
                st.write(f"**{t('your_answer')}** {user_text}")
            st.success(t("correct_answer", answer=correct_text))
        else:
            selected = st.session_state.selected_answer
            for i, option in enumerate(question["options"]):
                if i == correct_index:
                    st.success(f"✓ {option}")
                elif i == selected and selected != correct_index:
                    st.error(f"✗ {option}")
                else:
                    st.write(f"  {option}")

            if selected == correct_index:
                st.success(t("correct"))
            else:
                st.error(t("incorrect"))

        st.info(t("explanation", text=question['explanation']))

        if st.button(t("next_question"), type="primary"):
            st.session_state.current_index += 1
            st.session_state.answered = False
            st.session_state.selected_answer = None
            st.rerun()

    st.divider()
    if st.button(t("abandon_test")):
        reset_quiz()
        st.rerun()


def show_dashboard():
    """Show the results dashboard."""
    st.header(t("results_history"))

    user_id = st.session_state.user_id
    sessions = get_user_sessions(user_id)

    if not sessions:
        st.info(t("no_results_yet"))
        return

    # --- Sessions summary ---
    st.subheader(t("previous_sessions"))

    selected_session_ids = []

    for s in sessions:
        test_display = s["title"] or t("unknown_test")
        pct = (s["score"] / s["total"]) * 100 if s["total"] > 0 else 0
        date_str = s["date"][:16] if s["date"] else "—"
        wrong_count = s["total"] - s["score"]

        col1, col2 = st.columns([4, 1])
        with col1:
            label = f"{date_str} — {test_display}: {s['score']}/{s['total']} ({pct:.0f}%)"
            if wrong_count > 0:
                with st.expander(label):
                    wrong_refs = get_session_wrong_answers(s["id"])
                    if wrong_refs:
                        by_test = {}
                        for w in wrong_refs:
                            by_test.setdefault(w["test_id"], set()).add(w["question_id"])
                        wrong_questions = []
                        for tid, q_ids in by_test.items():
                            if tid:
                                wrong_questions.extend(get_test_questions_by_ids(tid, list(q_ids)))
                        for i, q in enumerate(wrong_questions, 1):
                            tag_display = q["tag"].replace("_", " ").title()
                            st.markdown(f"**{i}. {q['question']}**")
                            st.caption(t("topic", name=tag_display))
                            correct = q["options"][q["answer_index"]]
                            st.success(t("correct_answer", answer=correct))
                            st.info(t("explanation", text=q['explanation']))
                            st.write("---")
                    else:
                        st.write(t("no_wrong_details"))
            else:
                st.write(f"{label} ✓")
        with col2:
            if wrong_count > 0:
                if st.checkbox(t("select_checkbox"), key=f"sel_session_{s['id']}", label_visibility="collapsed"):
                    selected_session_ids.append(s["id"])

    # --- Practice from selected sessions ---
    if selected_session_ids:
        st.divider()
        all_wrong = []
        for sid in selected_session_ids:
            wrong_refs = get_session_wrong_answers(sid)
            for w in wrong_refs:
                all_wrong.append(w)

        seen = set()
        unique_wrong = []
        for w in all_wrong:
            key = (w["test_id"], w["question_id"])
            if key not in seen:
                seen.add(key)
                unique_wrong.append(w)

        st.write(t("wrong_selected", n=len(unique_wrong)))
        if st.button(t("practice_wrong"), type="primary"):
            _start_quiz_from_wrong(unique_wrong)


def _start_quiz_from_wrong(wrong_refs):
    """Start a quiz from a list of wrong question references."""
    by_test = {}
    for w in wrong_refs:
        by_test.setdefault(w["test_id"], set()).add(w["question_id"])

    quiz_questions = []
    test_id = None
    for tid, q_ids in by_test.items():
        if tid:
            questions = get_test_questions_by_ids(tid, list(q_ids))
            quiz_questions.extend(questions)
            test_id = tid

    if not quiz_questions:
        return

    random.shuffle(quiz_questions)
    tid = test_id or 0
    session_id = create_session(
        st.session_state.user_id, tid, 0, len(quiz_questions),
    )
    st.session_state.questions = shuffle_question_options(quiz_questions)
    st.session_state.current_index = 0
    st.session_state.score = 0
    st.session_state.answered = False
    st.session_state.show_result = False
    st.session_state.selected_answer = None
    st.session_state.wrong_questions = []
    st.session_state.round_history = []
    st.session_state.current_round = 1
    st.session_state.current_test_id = tid
    st.session_state.current_session_id = session_id
    st.session_state.session_score_saved = False
    st.session_state.quiz_started = True
    st.session_state.page = "Tests"
    st.rerun()


def show_create_test():
    """Show the create test form."""
    st.header(t("create_new_test"))

    if st.button(t("back")):
        st.session_state.page = "Tests"
        st.rerun()

    title = st.text_input(t("test_title"), key="new_test_title")
    description = st.text_area(t("description"), key="new_test_desc")
    language = st.selectbox(
        t("language"), options=LANGUAGE_OPTIONS,
        format_func=lambda x: _lang_display(x) if x else "—",
        key="new_test_lang",
    )

    uploaded_json = st.file_uploader(
        t("import_json"),
        type=["json"],
        key="new_test_json",
    )

    if st.button(t("create_test_btn"), type="primary"):
        if not title.strip():
            st.warning(t("title_required"))
        else:
            author = st.session_state.get("username", "")
            test_id = create_test(st.session_state.user_id, title.strip(), description.strip(), author, language)

            if uploaded_json is not None:
                import json
                try:
                    data = json.loads(uploaded_json.read())
                    questions_list = data if isinstance(data, list) else data.get("questions", [])
                    for i, q in enumerate(questions_list, 1):
                        add_question(
                            test_id, i,
                            q.get("tag", "general"),
                            q["question"],
                            q["options"],
                            q["answer_index"],
                            q.get("explanation", ""),
                            source="json_import",
                        )
                except (json.JSONDecodeError, KeyError) as e:
                    st.error(t("json_import_error", e=e))

            st.session_state.editing_test_id = test_id
            st.session_state.page = "Editar Test"
            st.rerun()


def show_test_editor():
    """Show the test editor page for editing metadata and questions."""
    test_id = st.session_state.get("editing_test_id")
    if not test_id:
        st.session_state.page = "Tests"
        st.rerun()
        return

    test = get_test(test_id)
    if not test:
        st.error(t("test_not_found"))
        return

    questions = get_test_questions(test_id)

    st.header(t("edit_colon", name=test['title']))

    if st.button(t("back")):
        if "editing_test_id" in st.session_state:
            del st.session_state.editing_test_id
        st.session_state.page = "Tests"
        st.rerun()

    # --- Metadata ---
    st.subheader(t("test_info"))
    new_title = st.text_input(t("title"), value=test["title"], key="edit_title")
    new_desc = st.text_area(t("description"), value=test["description"] or "", key="edit_desc")
    new_author = st.text_input(t("author_label"), value=test["author"] or "", key="edit_author")
    current_lang_index = LANGUAGE_OPTIONS.index(test.get("language", "")) if test.get("language", "") in LANGUAGE_OPTIONS else 0
    new_language = st.selectbox(
        t("language"), options=LANGUAGE_OPTIONS,
        index=current_lang_index,
        format_func=lambda x: _lang_display(x) if x else "—",
        key="edit_lang",
    )

    if st.button(t("save_info"), type="primary"):
        if not new_title.strip():
            st.warning(t("title_required"))
        else:
            update_test(test_id, new_title.strip(), new_desc.strip(), new_author.strip(), new_language)
            if "editing_test_id" in st.session_state:
                del st.session_state.editing_test_id
            st.session_state.selected_test = test_id
            st.session_state.page = "Configurar Test"
            st.rerun()

    st.divider()

    # --- Materials ---
    st.subheader(t("reference_materials_header"))

    materials = get_test_materials(test_id)
    for mat in materials:
        col_gen, col_mat, col_del = st.columns([1, 4, 0.5])
        with col_gen:
            if st.button(t("generate"), key=f"gen_mat_{mat['id']}"):
                next_num = get_next_question_num(test_id)
                mat_label = mat["title"] or t("no_title")
                for i in range(3):
                    add_question(
                        test_id, next_num + i, "general",
                        t("generated_question", name=mat_label, n=i+1),
                        [t("option_a"), t("option_b"), t("option_c"), t("option_d")],
                        0, t("generated_explanation"),
                        source=f"material:{mat['id']}",
                    )
                st.rerun()
        with col_mat:
            type_icons = {"pdf": "📄", "youtube": "▶️", "image": "🖼️", "url": "🔗"}
            icon = type_icons.get(mat["material_type"], "📎")
            label = mat["title"] or mat["url"] or t("no_title")
            if mat["material_type"] in ("youtube", "url") and mat["url"]:
                st.markdown(f"{icon} [{label}]({mat['url']})")
            elif mat["material_type"] == "image" and mat["file_data"]:
                st.write(f"{icon} {label}")
                st.image(mat["file_data"], width=200)
            elif mat["material_type"] == "pdf" and mat["file_data"]:
                st.download_button(
                    f"{icon} {label}",
                    data=mat["file_data"],
                    file_name=f"{label}.pdf",
                    key=f"dl_mat_{mat['id']}",
                )
            else:
                st.write(f"{icon} {label}")
        with col_del:
            if st.button("🗑️", key=f"del_mat_{mat['id']}"):
                delete_test_material(mat["id"])
                st.rerun()

    st.write(t("add_material_label"))
    mat_type = st.selectbox(t("material_type"), ["pdf", "youtube", "image", "url"],
                            format_func=lambda x: {"pdf": t("pdf"), "youtube": t("youtube"), "image": t("image"), "url": t("url_type")}[x],
                            key="new_mat_type")
    mat_title = st.text_input(t("material_title"), key="new_mat_title")

    mat_url = ""
    mat_file = None
    if mat_type in ("youtube", "url"):
        mat_url = st.text_input(t("url"), key="new_mat_url")
    else:
        file_types = ["pdf"] if mat_type == "pdf" else ["png", "jpg", "jpeg", "gif"]
        mat_file = st.file_uploader(t("file"), type=file_types, key="new_mat_file")

    if st.button(t("add_material_btn"), type="secondary"):
        file_data = mat_file.read() if mat_file else None
        if mat_type in ("youtube", "url") and not mat_url.strip():
            st.warning(t("url_required"))
        elif mat_type in ("pdf", "image") and not file_data:
            st.warning(t("file_required"))
        else:
            add_test_material(test_id, mat_type, mat_title.strip(), mat_url.strip(), file_data)
            st.rerun()

    st.divider()

    # --- Topics ---
    st.subheader(t("topics"))

    tags = get_test_tags(test_id)
    tag_counts = {}
    for q in questions:
        tag_counts[q["tag"]] = tag_counts.get(q["tag"], 0) + 1

    tag_edits = {}
    for tag in tags:
        count = tag_counts.get(tag, 0)
        confirm_key = f"confirm_del_tag_{tag}"

        if st.session_state.get(confirm_key):
            st.warning(t("delete_topic_confirm", tag=tag, n=count))
            col_del_q, col_blank, col_cancel = st.columns(3)
            with col_del_q:
                if st.button(t("delete_questions_btn"), key=f"deltag_delq_{tag}"):
                    delete_test_tag(test_id, tag, delete_questions=True)
                    del st.session_state[confirm_key]
                    st.rerun()
            with col_blank:
                if st.button(t("leave_blank"), key=f"deltag_blank_{tag}"):
                    delete_test_tag(test_id, tag, delete_questions=False)
                    del st.session_state[confirm_key]
                    st.rerun()
            with col_cancel:
                if st.button(t("cancel"), key=f"deltag_cancel_{tag}"):
                    del st.session_state[confirm_key]
                    st.rerun()
        else:
            col_name, col_count, col_del = st.columns([3, 1, 0.5])
            with col_name:
                new_name = st.text_input(t("topic_label"), value=tag, key=f"tag_name_{tag}", label_visibility="collapsed")
                tag_edits[tag] = new_name
            with col_count:
                st.caption(t("n_questions_abbrev", n=count))
            with col_del:
                if st.button("🗑️", key=f"del_tag_{tag}"):
                    st.session_state[confirm_key] = True
                    st.rerun()

    if tag_edits:
        if st.button(t("save_topic_changes")):
            for old_tag, new_tag in tag_edits.items():
                if new_tag.strip() != old_tag and new_tag.strip():
                    rename_test_tag(test_id, old_tag, new_tag.strip())
            st.rerun()

    st.write(t("add_topic_label"))
    col_new_tag, col_add_tag = st.columns([3, 1])
    with col_new_tag:
        new_tag_name = st.text_input(t("topic_label"), key="new_tag_name", label_visibility="collapsed", placeholder=t("topic_name_placeholder"))
    with col_add_tag:
        if st.button(t("add_btn")):
            if new_tag_name and new_tag_name.strip():
                next_num = get_next_question_num(test_id)
                add_question(test_id, next_num, new_tag_name.strip(), t("new_question_text"), [t("option_a"), t("option_b"), t("option_c"), t("option_d")], 0, "")
                st.rerun()

    st.divider()

    # --- Questions ---
    st.subheader(t("questions_header", n=len(questions)))

    if st.button(t("add_question")):
        next_num = get_next_question_num(test_id)
        add_question(test_id, next_num, "general", t("new_question_text"), [t("option_a"), t("option_b"), t("option_c"), t("option_d")], 0, "")
        st.rerun()

    for q in questions:
        with st.expander(f"#{q['id']} — {q['question'][:80]}"):
            q_key = f"q_{q['db_id']}"
            source = q.get("source", "manual")
            if source == "manual":
                source_label = t("source_manual")
            elif source == "json_import":
                source_label = t("source_json")
            elif source.startswith("material:"):
                source_label = t("source_material", id=source.split(':')[1])
            else:
                source_label = source
            st.caption(t("source", name=source_label))
            q_tag = st.text_input(t("topic_label"), value=q["tag"], key=f"{q_key}_tag")
            q_text = st.text_area(t("question_label"), value=q["question"], key=f"{q_key}_text")
            q_explanation = st.text_area(t("explanation_label"), value=q.get("explanation", ""), key=f"{q_key}_expl")

            st.write(t("options_header"))
            options = []
            for oi in range(len(q["options"])):
                opt = st.text_input(t("option_n", n=oi + 1), value=q["options"][oi], key=f"{q_key}_opt_{oi}")
                options.append(opt)

            col_add, col_rm = st.columns(2)
            with col_add:
                if st.button(t("add_option"), key=f"{q_key}_add_opt"):
                    new_opts = q["options"] + [t("option_n", n=len(q['options']) + 1)]
                    update_question(q["db_id"], q["tag"], q["question"], new_opts, q["answer_index"], q.get("explanation", ""))
                    st.rerun()
            with col_rm:
                if len(q["options"]) > 2:
                    if st.button(t("remove_option"), key=f"{q_key}_rm_opt"):
                        new_opts = q["options"][:-1]
                        new_ans = min(q["answer_index"], len(new_opts) - 1)
                        update_question(q["db_id"], q["tag"], q["question"], new_opts, new_ans, q.get("explanation", ""))
                        st.rerun()

            q_answer = st.selectbox(
                t("correct_answer_select"),
                range(len(options)),
                index=q["answer_index"],
                format_func=lambda i: options[i] if i < len(options) else "",
                key=f"{q_key}_ans",
            )

            col_save, col_del = st.columns(2)
            with col_save:
                if st.button(t("save_question"), key=f"{q_key}_save", type="primary"):
                    update_question(q["db_id"], q_tag.strip(), q_text.strip(), options, q_answer, q_explanation.strip())
                    st.success(t("question_updated"))
                    st.rerun()
            with col_del:
                if st.button(t("delete_question"), key=f"{q_key}_del"):
                    delete_question(q["db_id"])
                    st.rerun()

    st.divider()

    # --- Delete test ---
    st.subheader(t("danger_zone"))
    if st.button(t("delete_full_test"), type="secondary"):
        st.session_state[f"confirm_delete_{test_id}"] = True

    if st.session_state.get(f"confirm_delete_{test_id}"):
        st.warning(t("confirm_delete"))
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button(t("yes_delete"), type="primary"):
                delete_test(test_id)
                if "editing_test_id" in st.session_state:
                    del st.session_state.editing_test_id
                st.session_state.page = "Tests"
                st.rerun()
        with col_no:
            if st.button(t("cancel")):
                del st.session_state[f"confirm_delete_{test_id}"]
                st.rerun()


def _get_avatar_html(avatar_bytes, size=35):
    """Return HTML for a circular avatar image, or initials if no avatar."""
    if avatar_bytes:
        b64 = base64.b64encode(avatar_bytes).decode()
        return f'<img src="data:image/png;base64,{b64}" style="width:{size}px;height:{size}px;border-radius:50%;object-fit:cover;">'
    initial = st.session_state.get("username", "?")[0].upper()
    return (
        f'<div style="width:{size}px;height:{size}px;border-radius:50%;'
        f'background:#4A90D9;color:white;display:flex;align-items:center;'
        f'justify-content:center;font-size:{size//2}px;font-weight:bold;">'
        f'{initial}</div>'
    )


def _load_profile_to_session():
    """Load user profile from DB into session state if not cached."""
    if "profile_loaded" not in st.session_state:
        profile = get_user_profile(st.session_state.user_id)
        st.session_state.display_name = profile["display_name"] or st.session_state.username
        st.session_state.avatar_bytes = profile["avatar"]
        st.session_state.profile_loaded = True


def show_profile():
    """Show profile settings page."""
    st.header(t("profile_header"))

    profile = get_user_profile(st.session_state.user_id)
    current_name = profile["display_name"] or st.session_state.username
    current_avatar = profile["avatar"]

    if current_avatar:
        st.image(current_avatar, width=120)
    else:
        st.markdown(_get_avatar_html(None, size=120), unsafe_allow_html=True)

    st.divider()

    display_name = st.text_input(t("display_name"), value=current_name, key="profile_name_input")

    uploaded_file = st.file_uploader(
        t("upload_photo"),
        type=["png", "jpg", "jpeg"],
        key="profile_avatar_upload",
    )

    if st.button(t("save"), type="primary"):
        avatar_data = None
        if uploaded_file is not None:
            avatar_data = uploaded_file.read()
        elif current_avatar:
            avatar_data = current_avatar

        if avatar_data is not None:
            update_user_profile(st.session_state.user_id, display_name, avatar_data)
        else:
            update_user_profile(st.session_state.user_id, display_name)

        st.session_state.display_name = display_name
        st.session_state.avatar_bytes = avatar_data
        st.session_state.username = display_name
        st.success(t("profile_updated"))
        st.session_state.page = st.session_state.get("prev_page", "Tests")
        st.rerun()


def show_programs():
    """Show the program catalog."""
    user_id = st.session_state.user_id
    programs = get_all_programs(user_id)

    st.header(t("programs_header"))

    if st.button(t("create_program"), type="secondary"):
        st.session_state.page = "Crear Programa"
        st.rerun()

    if not programs:
        st.info(t("no_programs"))
        return

    for prog in programs:
        with st.container(border=True):
            col_info, col_btn = st.columns([4, 1])
            with col_info:
                st.subheader(prog["title"])
                if prog["description"]:
                    st.write(prog["description"])
                st.caption(t("n_tests", n=prog['test_count']))
            with col_btn:
                if st.button(t("select"), key=f"prog_sel_{prog['id']}", use_container_width=True):
                    st.session_state.selected_program = prog["id"]
                    st.session_state.page = "Configurar Programa"
                    st.rerun()
                if st.button(t("edit"), key=f"prog_edit_{prog['id']}", use_container_width=True):
                    st.session_state.editing_program_id = prog["id"]
                    st.session_state.page = "Editar Programa"
                    st.rerun()


def show_create_program():
    """Show create program form."""
    st.header(t("create_new_program"))

    if st.button(t("back")):
        st.session_state.page = "Programas"
        st.rerun()

    title = st.text_input(t("program_title"), key="new_prog_title")
    description = st.text_area(t("description"), key="new_prog_desc")

    if st.button(t("create_program_btn"), type="primary"):
        if not title.strip():
            st.warning(t("title_required"))
        else:
            program_id = create_program(st.session_state.user_id, title.strip(), description.strip())
            st.session_state.editing_program_id = program_id
            st.session_state.page = "Editar Programa"
            st.rerun()


def show_program_editor():
    """Show program editor page."""
    program_id = st.session_state.get("editing_program_id")
    if not program_id:
        st.session_state.page = "Programas"
        st.rerun()
        return

    prog = get_program(program_id)
    if not prog:
        st.error(t("program_not_found"))
        return

    st.header(t("edit_colon", name=prog['title']))

    if st.button(t("back")):
        if "editing_program_id" in st.session_state:
            del st.session_state.editing_program_id
        st.session_state.page = "Programas"
        st.rerun()

    # --- Metadata ---
    st.subheader(t("program_info"))
    new_title = st.text_input(t("title"), value=prog["title"], key="edit_prog_title")
    new_desc = st.text_area(t("description"), value=prog["description"] or "", key="edit_prog_desc")

    if st.button(t("save_info"), type="primary"):
        if not new_title.strip():
            st.warning(t("title_required"))
        else:
            update_program(program_id, new_title.strip(), new_desc.strip())
            st.success(t("info_updated"))
            st.rerun()

    st.divider()

    # --- Tests in program ---
    st.subheader(t("tests_included"))

    prog_tests = get_program_tests(program_id)
    if prog_tests:
        for pt in prog_tests:
            col_info, col_rm = st.columns([5, 1])
            with col_info:
                st.write(f"**{pt['title']}** ({t('n_questions', n=pt['question_count'])})")
            with col_rm:
                if st.button(t("remove"), key=f"rm_pt_{pt['id']}"):
                    remove_test_from_program(program_id, pt["id"])
                    st.rerun()
    else:
        st.info(t("no_tests_in_program"))

    # Add test
    all_tests = get_all_tests(st.session_state.user_id)
    current_test_ids = {pt["id"] for pt in prog_tests}
    available_tests = [tt for tt in all_tests if tt["id"] not in current_test_ids]

    if available_tests:
        st.write(t("add_test_label"))
        test_options = {tt["id"]: f"{tt['title']} ({t('n_questions_abbrev', n=tt['question_count'])})" for tt in available_tests}
        selected_test_id = st.selectbox(
            t("test_label"), options=list(test_options.keys()),
            format_func=lambda x: test_options[x],
            key="add_prog_test",
        )
        if st.button(t("add_test_btn")):
            add_test_to_program(program_id, selected_test_id)
            st.rerun()

    st.divider()

    # --- Delete program ---
    st.subheader(t("danger_zone"))
    if st.button(t("delete_program"), type="secondary"):
        st.session_state[f"confirm_delete_prog_{program_id}"] = True

    if st.session_state.get(f"confirm_delete_prog_{program_id}"):
        st.warning(t("confirm_delete"))
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button(t("yes_delete"), key="prog_del_yes", type="primary"):
                delete_program(program_id)
                if "editing_program_id" in st.session_state:
                    del st.session_state.editing_program_id
                st.session_state.page = "Programas"
                st.rerun()
        with col_no:
            if st.button(t("cancel"), key="prog_del_no"):
                del st.session_state[f"confirm_delete_prog_{program_id}"]
                st.rerun()


def show_program_config():
    """Show configuration for a program before starting quiz."""
    program_id = st.session_state.get("selected_program")
    if not program_id:
        st.session_state.page = "Programas"
        st.rerun()
        return

    prog = get_program(program_id)
    if not prog:
        st.error(t("program_not_found"))
        return

    questions = get_program_questions(program_id)
    tags = get_program_tags(program_id)
    prog_tests = get_program_tests(program_id)

    st.header(prog["title"])
    if prog.get("description"):
        st.write(prog["description"])

    st.caption(t("n_tests_n_questions", nt=len(prog_tests), nq=len(questions)))

    with st.expander(t("tests_included")):
        for pt in prog_tests:
            st.write(f"- **{pt['title']}** ({t('n_questions', n=pt['question_count'])})")

    if st.button(t("back_to_programs")):
        if "selected_program" in st.session_state:
            del st.session_state.selected_program
        st.session_state.page = "Programas"
        st.rerun()

    if not questions:
        st.warning(t("no_program_questions"))
        return

    st.subheader(t("configuration"))

    num_questions = st.number_input(
        t("num_questions"),
        min_value=1,
        max_value=len(questions),
        value=min(25, len(questions)),
    )

    st.write(t("topics_to_include"))
    selected_tags = []
    cols = st.columns(2)
    for i, tag in enumerate(tags):
        tag_display = tag.replace("_", " ").title()
        if cols[i % 2].checkbox(tag_display, value=True, key=f"prog_tag_{tag}"):
            selected_tags.append(tag)

    if not selected_tags:
        st.warning(t("select_at_least_one_topic"))
    else:
        filtered_count = len([q for q in questions if q["tag"] in selected_tags])
        st.info(t("available_questions_with_topics", n=filtered_count))

        if st.button(t("start_test"), type="primary"):
            stats = get_question_stats(st.session_state.user_id, program_id) if _is_logged_in() else None
            quiz_questions = select_balanced_questions(
                questions, selected_tags, num_questions, stats
            )
            session_id = None
            if _is_logged_in():
                session_id = create_session(
                    st.session_state.user_id, 0,
                    0, len(quiz_questions),
                )
            st.session_state.questions = shuffle_question_options(quiz_questions)
            st.session_state.current_index = 0
            st.session_state.score = 0
            st.session_state.answered = False
            st.session_state.show_result = False
            st.session_state.selected_answer = None
            st.session_state.wrong_questions = []
            st.session_state.round_history = []
            st.session_state.current_round = 1
            st.session_state.current_test_id = 0
            st.session_state.current_session_id = session_id
            st.session_state.quiz_started = True
            st.session_state.page = "Programas"
            st.rerun()


def main():
    st.set_page_config(page_title="Knowting", page_icon="📚")

    _try_login()

    if _is_logged_in():
        _load_profile_to_session()

    if "page" not in st.session_state:
        st.session_state.page = "Tests"

    logged_in = _is_logged_in()

    # Top bar: title + avatar/login
    col_title, col_avatar = st.columns([6, 1])
    with col_title:
        st.title("Knowting")
        st.subheader(f"*{t('tagline')}*")
    with col_avatar:
        if logged_in:
            avatar_bytes = st.session_state.get("avatar_bytes")
            display_name = st.session_state.get("display_name", st.session_state.username)
            popover_label = "👤"
            with st.popover(popover_label):
                if avatar_bytes:
                    st.image(avatar_bytes, width=60)
                st.write(f"**{display_name}**")
                st.divider()
                if st.button(t("profile"), key="menu_profile", use_container_width=True):
                    st.session_state.prev_page = st.session_state.page
                    st.session_state.page = "Perfil"
                    st.rerun()
                if st.button(t("logout"), key="menu_logout", use_container_width=True):
                    for key in list(st.session_state.keys()):
                        del st.session_state[key]
                    st.logout()
                    st.rerun()
        else:
            st.button(t("login"), on_click=st.login, type="secondary")

    # Sidebar navigation
    with st.sidebar:
        # Language toggle
        current_lang = st.session_state.get("lang", "es")
        current_idx = UI_LANGUAGES.index(current_lang) if current_lang in UI_LANGUAGES else 0
        selected_ui_lang = st.selectbox(
            "🌐", options=UI_LANGUAGES,
            index=current_idx,
            format_func=lambda x: UI_LANG_LABELS.get(x, x),
            key="lang_toggle",
            label_visibility="collapsed",
        )
        if selected_ui_lang != current_lang:
            st.session_state.lang = selected_ui_lang
            st.rerun()

        st.markdown("---")
        nav_items = [("📝", "Tests", t("tests"))]
        if logged_in:
            nav_items.append(("📊", "Dashboard", t("dashboard")))
            nav_items.append(("📚", "Programas", t("programs")))
        for icon, page_id, display in nav_items:
            is_active = st.session_state.page == page_id
            btn_type = "primary" if is_active else "secondary"
            if st.button(f"{icon}  {display}", key=f"nav_{page_id}", use_container_width=True, type=btn_type):
                st.session_state.page = page_id
                st.rerun()
        st.markdown("---")

    if "quiz_started" not in st.session_state:
        st.session_state.quiz_started = False

    if logged_in and st.session_state.page == "Perfil":
        show_profile()
    elif logged_in and st.session_state.page == "Dashboard" and not st.session_state.quiz_started:
        show_dashboard()
    elif st.session_state.page == "Configurar Test":
        show_test_config()
    elif logged_in and st.session_state.page == "Crear Test":
        show_create_test()
    elif logged_in and st.session_state.page == "Editar Test":
        show_test_editor()
    elif logged_in and st.session_state.page == "Programas" and not st.session_state.quiz_started:
        show_programs()
    elif logged_in and st.session_state.page == "Crear Programa":
        show_create_program()
    elif logged_in and st.session_state.page == "Editar Programa":
        show_program_editor()
    elif logged_in and st.session_state.page == "Configurar Programa":
        show_program_config()
    elif st.session_state.quiz_started:
        show_quiz()
    else:
        show_test_catalog()


if __name__ == "__main__":
    main()
