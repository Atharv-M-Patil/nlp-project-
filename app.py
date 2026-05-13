
import json
import os
import re
from html import unescape
from pathlib import Path
from difflib import SequenceMatcher
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import streamlit as st

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False


BASE_DIR = Path(__file__).resolve().parent
DATASET_PATH = BASE_DIR / "sample_dataset_1.json"
KNOWLEDGE_CACHE_PATH = BASE_DIR / "knowledge_cache.json"


def load_json_file(path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return default


def save_json_file(path, data):
    try:
        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
    except OSError:
        pass


def strip_html(text):
    cleaned = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(cleaned)).strip()


def normalize(text):
    return re.sub(r"[^a-z0-9\s]", " ", text.lower()).strip()


def tokenize(text):
    return set(normalize(text).split())


def build_index(dataset):
    items = []
    for topic in dataset.get("data", []):
        for paragraph in topic.get("paragraphs", []):
            context = paragraph.get("context", "")
            for qa in paragraph.get("qas", []):
                answers = qa.get("answers", [])
                if not answers:
                    continue

                question = qa.get("question", "")
                answer = answers[0].get("text", "")
                items.append(
                    {
                        "title": topic.get("title", ""),
                        "question": question,
                        "answer": answer,
                        "context": context,
                        "search_text": f"{question} {context} {answer} {topic.get('title', '')}",
                    }
                )
    return items


def build_cache_index(cache_data):
    items = []
    for entry in cache_data.get("entries", []):
        question = entry.get("question", "")
        answer = entry.get("answer", "")
        source = entry.get("source", "")
        items.append(
            {
                "title": source,
                "question": question,
                "answer": answer,
                "context": entry.get("context", ""),
                "search_text": f"{question} {answer} {source}",
            }
        )
    return items


def make_cache_key(question):
    return normalize(question)


def ensure_cache_structure(cache_data):
    if not isinstance(cache_data, dict):
        cache_data = {}
    cache_data.setdefault("entries", [])
    cache_data.setdefault("index", {})
    return cache_data


def cache_answer(question, answer, source, context=""):
    global knowledge_items

    cache_key = make_cache_key(question)
    if not cache_key or not answer:
        return

    existing = knowledge_cache["index"].get(cache_key)
    entry = {
        "question": question,
        "answer": answer,
        "source": source,
        "context": context,
        "cache_key": cache_key,
    }

    if existing is not None:
        knowledge_cache["entries"][existing] = entry
    else:
        knowledge_cache["index"][cache_key] = len(knowledge_cache["entries"])
        knowledge_cache["entries"].append(entry)

    knowledge_items = build_cache_index(knowledge_cache)
    save_json_file(KNOWLEDGE_CACHE_PATH, knowledge_cache)


def get_cache_item(user_question):
    if not knowledge_items:
        return None, 0.0

    best_item = max(
        knowledge_items,
        key=lambda item: (
            similarity(user_question, item["question"]),
            similarity(user_question, item["context"]),
            similarity(user_question, item["search_text"]),
        ),
    )

    best_score = max(
        similarity(user_question, best_item["question"]),
        similarity(user_question, best_item["context"]),
        similarity(user_question, best_item["search_text"]),
    )
    return best_item, best_score


def similarity(query, text):
    query_norm = normalize(query)
    text_norm = normalize(text)
    if not query_norm or not text_norm:
        return 0.0

    query_tokens = tokenize(query)
    text_tokens = tokenize(text)
    token_score = len(query_tokens & text_tokens) / max(len(query_tokens), 1)
    sequence_score = SequenceMatcher(None, query_norm, text_norm).ratio()
    return (0.65 * sequence_score) + (0.35 * token_score)


def has_meaningful_overlap(user_question, item):
    stopwords = {
        "a",
        "an",
        "and",
        "explain",
        "for",
        "how",
        "in",
        "is",
        "me",
        "of",
        "on",
        "simple",
        "tell",
        "the",
        "to",
        "what",
        "when",
        "where",
        "who",
        "why",
        "words",
    }

    query_tokens = tokenize(user_question) - stopwords
    item_tokens = (
        tokenize(item.get("question", ""))
        | tokenize(item.get("context", ""))
        | tokenize(item.get("search_text", ""))
    ) - stopwords
    return bool(query_tokens & item_tokens)


def get_best_item(user_question):
    if not qa_items:
        return None, 0.0

    best_item = max(
        qa_items,
        key=lambda item: (
            similarity(user_question, item["question"]),
            similarity(user_question, item["context"]),
            similarity(user_question, item["search_text"]),
        ),
    )

    best_score = max(
        similarity(user_question, best_item["question"]),
        similarity(user_question, best_item["context"]),
        similarity(user_question, best_item["search_text"]),
    )
    return best_item, best_score


def generate_fallback_answer(user_question):
    normalized = normalize(user_question)

    if any(word in normalized for word in ["color of apple", "colour of apple", "what color is apple", "what colour is apple"]):
        return "Apples are commonly red, green, or yellow, depending on the variety."

    if "joke" in normalized:
        return "Why did the computer keep freezing? Because it forgot to close its windows."

    if normalized in {"hi", "hello", "hey"}:
        return "Hello. Ask me a factual question, and I’ll look it up for you."

    if normalized.startswith("what is "):
        subject = user_question[8:].strip(" ?.")
        if subject:
            return f"{subject} is a topic I do not have a direct dataset fact for, but I can help explain it if you want a simpler definition or examples."

    if normalized.startswith("who is ") or normalized.startswith("who was "):
        subject = user_question.split(" ", 2)[-1].strip(" ?.")
        if subject:
            return f"I do not have a direct dataset entry for {subject}, but I can help summarize who they are if you want."

    if normalized.startswith("how ") or normalized.startswith("why "):
        topic = user_question.strip(" ?.")
        return f"I do not have a direct dataset answer for '{topic}', but I can help reason through it step by step."

    return (
        "I do not have a direct dataset match for that question, but I can still help. "
        "Try asking in a simpler way, or I can explain the topic in plain language."
    )


def is_likely_factual_query(user_question):
    normalized = normalize(user_question)
    factual_starts = (
        "what is ",
        "what are ",
        "who is ",
        "who was ",
        "where is ",
        "where was ",
        "when is ",
        "when was ",
        "how is ",
        "how are ",
        "capital of ",
        "meaning of ",
        "define ",
        "explain ",
        "national sport of ",
        "national game of ",
        "facts about ",
        "about ",
    )
    return normalized.startswith(factual_starts) or " capital of " in f" {normalized} "


def build_web_queries(user_question):
    stripped = user_question.strip(" ?.")
    if not stripped:
        return []

    queries = [stripped]
    normalized = normalize(user_question)

    prefix_patterns = [
        "what is ",
        "what are ",
        "who is ",
        "who was ",
        "where is ",
        "where was ",
        "when is ",
        "when was ",
        "how is ",
        "how are ",
    ]
    for prefix in prefix_patterns:
        if normalized.startswith(prefix):
            candidate = stripped[len(prefix):].strip(" ?.")
            if candidate and candidate not in queries:
                queries.append(candidate)

    if normalized.startswith("capital of "):
        country = stripped[len("capital of "):].strip(" ?.")
        if country:
            capital_query = f"Capital of {country}"
            if capital_query not in queries:
                queries.insert(0, capital_query)

    if " machine learning" in normalized or normalized == "machine learning":
        if "machine learning" not in queries:
            queries.insert(0, "machine learning")

    return queries


def fetch_wikipedia_answer(user_question):
    headers = {"User-Agent": "Mozilla/5.0"}
    normalized = normalize(user_question)
    capital_country = ""
    if normalized.startswith("capital of "):
        capital_country = user_question.strip(" ?.")[len("capital of "):].strip()

    for query in build_web_queries(user_question):
        try:
            search_url = (
                "https://en.wikipedia.org/w/api.php?action=opensearch&search="
                f"{quote(query)}&limit=5&namespace=0&format=json"
            )
            request = Request(search_url, headers=headers)
            with urlopen(request, timeout=10) as response:
                search_data = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            continue

        titles = search_data[1] if len(search_data) > 1 else []
        for title in titles[:3]:
            try:
                summary_url = (
                    "https://en.wikipedia.org/api/rest_v1/page/summary/"
                    f"{quote(title.replace(' ', '_'))}"
                )
                request = Request(summary_url, headers=headers)
                with urlopen(request, timeout=10) as response:
                    summary_data = json.loads(response.read().decode("utf-8"))
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
                continue

            extract = summary_data.get("extract", "").strip()
            if extract:
                if extract.lower().startswith("python may refer to"):
                    continue

                if capital_country:
                    capital_match = re.search(
                        r"(?:current )?capital city is ([^.]+)",
                        extract,
                        flags=re.IGNORECASE,
                    )
                    if capital_match:
                        capital = capital_match.group(1).strip().rstrip(".")
                        return {
                            "answer": f"The capital of {capital_country} is {capital}.",
                            "source": title,
                        }

                return {
                    "answer": extract,
                    "source": title,
                }

    return None


def fetch_google_answer(user_question):
    """Fetch answer using Google Custom Search API."""
    if not GOOGLE_API_AVAILABLE:
        return None

    api_key = os.getenv("GOOGLE_API_KEY")
    search_engine_id = os.getenv("GOOGLE_SEARCH_ENGINE_ID")

    if not api_key or not search_engine_id:
        return None

    try:
        service = build("customsearch", "v1", developerKey=api_key)
        query = user_question.strip(" ?.")
        if not query:
            return None

        result = service.cse().list(q=query, cx=search_engine_id, num=3).execute()
        items = result.get("items", [])

        for item in items:
            snippet = item.get("snippet", "").strip()
            title = item.get("title", "").strip()
            if snippet:
                return {
                    "answer": snippet,
                    "source": title or "Google Search",
                }

        return None
    except (HttpError, Exception):
        return None


def fetch_duckduckgo_answer(user_question):
    headers = {"User-Agent": "Mozilla/5.0"}
    query = user_question.strip(" ?.")
    if not query:
        return None

    try:
        search_url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
        request = Request(search_url, headers=headers)
        with urlopen(request, timeout=10) as response:
            page_html = response.read().decode("utf-8", errors="ignore")
    except (HTTPError, URLError, TimeoutError):
        return None

    result_blocks = re.split(r'<div class="result results_links.*?>', page_html)
    for block in result_blocks[1:6]:
        title_match = re.search(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not title_match:
            continue

        href = title_match.group(1).strip()
        title = strip_html(title_match.group(2))
        snippet_match = re.search(
            r'class="result__snippet"[^>]*>(.*?)</(?:div|a)>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        snippet = strip_html(snippet_match.group(1)) if snippet_match else ""

        if "duckduckgo.com" in href.lower():
            continue

        if title.lower().startswith("python may refer to"):
            continue

        text = snippet or title
        if text:
            return {
                "answer": text,
                "source": title or "DuckDuckGo",
            }

    return None


def get_special_topic_answer(user_question):
    normalized = normalize(user_question)
    if "national sport of india" in normalized or "national game of india" in normalized:
        return {
            "answer": (
                "India does not have an official national sport. Hockey is often associated with India historically, "
                "but it is not officially designated as the national sport."
            ),
            "source": "general-knowledge",
        }
    return None


def get_answer(user_question):
    special_answer = get_special_topic_answer(user_question)
    if special_answer:
        cache_answer(user_question, special_answer["answer"], special_answer["source"])
        return {
            "answer": special_answer["answer"],
            "matched_question": "",
            "confidence": 1.0,
            "context": "",
            "is_direct": False,
            "source": special_answer["source"],
        }

    best_item, score = get_best_item(user_question)
    if best_item:
        answer = best_item["answer"] or best_item["context"] or "No answer found."
        norm_q = normalize(user_question)
        norm_best_q = normalize(best_item.get("question", ""))
        exact_match = bool(norm_q and norm_best_q and (norm_q == norm_best_q or norm_q in norm_best_q or norm_best_q in norm_q))
        overlap = has_meaningful_overlap(user_question, best_item)

        # Prefer dataset answers when there's an exact match or meaningful overlap.
        # Allow slightly lower similarity when overlap exists to avoid spurious web fallbacks.
        is_direct = False
        if exact_match:
            is_direct = True
        elif overlap and score >= 0.18:
            is_direct = True
        elif score >= 0.35 and overlap:
            is_direct = True

        if is_direct:
            return {
                "answer": answer,
                "matched_question": best_item["question"],
                "confidence": score,
                "context": best_item["context"],
                "is_direct": True,
                "source": "dataset",
            }

    cache_item, cache_score = get_cache_item(user_question)
    if cache_item and cache_score >= 0.9:
        return {
            "answer": cache_item["answer"],
            "matched_question": cache_item["question"],
            "confidence": cache_score,
            "context": cache_item["context"],
            "is_direct": True,
            "source": cache_item["title"] or "cache",
        }

    normalized = normalize(user_question)
    if normalized in {"hi", "hello", "hey"} or "joke" in normalized:
        message = generate_fallback_answer(user_question)
        return {
            "answer": message,
            "matched_question": "",
            "confidence": 0.0,
            "context": "",
            "is_direct": False,
            "source": "fallback",
        }

    web_answer = None
    if is_likely_factual_query(user_question):
        web_answer = fetch_wikipedia_answer(user_question)
    if not web_answer:
        web_answer = fetch_google_answer(user_question)
    if not web_answer:
        web_answer = fetch_duckduckgo_answer(user_question)

    if web_answer:
        cache_answer(user_question, web_answer["answer"], web_answer["source"])
        return {
            "answer": web_answer["answer"],
            "matched_question": "",
            "confidence": 0.0,
            "context": "",
            "is_direct": False,
            "source": web_answer["source"],
        }

    message = generate_fallback_answer(user_question)

    return {
        "answer": message,
        "matched_question": best_item["question"] if best_item else "",
        "confidence": score if best_item else 0.0,
        "context": best_item["context"] if best_item else "",
        "is_direct": False,
        "source": "fallback",
    }


# Load dataset
data = load_json_file(DATASET_PATH, {"data": []})

knowledge_cache = ensure_cache_structure(
    load_json_file(KNOWLEDGE_CACHE_PATH, {"entries": [], "index": {}})
)

qa_items = build_index(data)
knowledge_items = build_cache_index(knowledge_cache)


APP_CSS = """
<style>
    .stApp {
        background:
            radial-gradient(circle at top left, rgba(0, 153, 255, 0.18), transparent 30%),
            radial-gradient(circle at top right, rgba(0, 194, 145, 0.14), transparent 25%),
            linear-gradient(180deg, #f7fbff 0%, #eef5ff 100%);
    }

    .block-container {
        max-width: 920px;
        padding-top: 2rem;
        padding-bottom: 2rem;
    }

    .hero {
        background: rgba(255, 255, 255, 0.72);
        border: 1px solid rgba(15, 23, 42, 0.08);
        border-radius: 24px;
        padding: 1.4rem 1.5rem;
        box-shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
        backdrop-filter: blur(12px);
        margin-bottom: 1rem;
    }

    .hero h1 {
        margin: 0;
        font-size: 2.2rem;
        line-height: 1.1;
    }

    .hero p {
        margin: 0.5rem 0 0;
        color: #475569;
        font-size: 1rem;
    }

    .hint-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 0.75rem;
        margin: 0.9rem 0 1.2rem;
    }

    .hint-card {
        background: rgba(255, 255, 255, 0.85);
        border: 1px solid rgba(15, 23, 42, 0.08);
        border-radius: 16px;
        padding: 0.85rem 1rem;
        color: #0f172a;
        font-size: 0.95rem;
    }

    div[data-testid="stChatMessage"] {
        border-radius: 18px;
        padding: 0.25rem 0.4rem;
        margin-bottom: 0.55rem;
    }

    div[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] {
        color: #0f172a;
    }

    div[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p {
        color: #0f172a;
        font-size: 1rem;
        line-height: 1.5;
    }

    div[data-testid="stChatMessage"] svg {
        color: #0f172a;
    }

    div[data-testid="stChatMessage"] > div {
        background: rgba(255, 255, 255, 0.88);
        border: 1px solid rgba(15, 23, 42, 0.08);
        border-radius: 18px;
        padding: 0.25rem 0.35rem;
    }
</style>
"""


def main():
    st.set_page_config(page_title="Chat QA", page_icon="🤖")
    st.markdown(APP_CSS, unsafe_allow_html=True)

    st.markdown(
        """
        <div class="hero">
            <h1>🤖 Chat QA System</h1>
            <p>Ask any question. The app will always return the closest available answer from the dataset.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="hint-grid">
            <div class="hint-card">Try: What is artificial intelligence?</div>
            <div class="hint-card">Try: Explain AI in simple words</div>
            <div class="hint-card">Try: What does machine intelligence mean?</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": "Ask me anything. I will answer from the dataset first, then try live web knowledge for broader questions.",
            }
        ]

    # Display chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    # Input
    user_input = st.chat_input("Ask something...")

    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})

        result = get_answer(user_input)
        answer_text = result["answer"]
        if result["is_direct"] and result["matched_question"]:
            answer_text = (
                f"{answer_text}\n\nMatched question: {result['matched_question']}"
            )
            if result["confidence"]:
                answer_text += f"\nConfidence: {result['confidence']:.2f}"
        elif result.get("source") and result["source"] not in {"fallback", "dataset"}:
            answer_text = f"{answer_text}\n\nSource: Wikipedia - {result['source']}"

        st.session_state.messages.append({"role": "assistant", "content": answer_text})

        st.rerun()


if __name__ == "__main__":
    main()
