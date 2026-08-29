import os
import sys
import json
import random
import time
import logging
import urllib.parse
import re
from io import BytesIO
from datetime import datetime
from dotenv import load_dotenv
import requests
from PIL import Image

# =============================================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('autopost.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# =============================================================================
# ЗАГРУЗКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ
# =============================================================================
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID', '').strip()
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
UNSPLASH_ACCESS_KEY = os.getenv('UNSPLASH_ACCESS_KEY', '').strip()

if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, GEMINI_API_KEY, UNSPLASH_ACCESS_KEY]):
    logger.error("❌ Не все переменные заданы! Проверь .env файл или Secrets в GitHub:")
    logger.error("   TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, GEMINI_API_KEY, UNSPLASH_ACCESS_KEY")
    sys.exit(1)

# =============================================================================
# КОНФИГУРАЦИЯ
# =============================================================================
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'topics_history.json')
MEMORY_DEPTH = 4  # не повторять подтемы ближайшие ~4 недели

# ЛИМИТ TELEGRAM: caption к фото = 1024 символа ВМЕСТЕ с HTML-тегами
# Оставляем запас ~70 символов на всякий случай
TELEGRAM_CAPTION_LIMIT = 950

# АКТУАЛЬНЫЕ МОДЕЛИ GEMINI (август 2026)
TEXT_MODELS = [
    "gemini-3.6-flash",       # Актуальная модель (рекомендована Google)
    "gemini-flash-latest",    # Алиас — всегда указывает на последнюю flash-модель
    "gemini-2.5-flash-lite",  # Легкая версия как fallback
]

# =============================================================================
# ТЕМЫ ПО ДНЯМ НЕДЕЛИ — КАНАЛ "СПОРТПИТ БЕЗ ВОДЫ"
# =============================================================================
THEMES = {
    0: {
        "rubric": "Разбор добавки",
        "format_hint": "полный независимый разбор одной конкретной добавки/вещества по шаблону",
        "topics": [
            "Креатин моногидрат: работает или маркетинг",
            "Сывороточный протеин (whey): что реально даёт",
            "BCAA: нужны ли отдельно от еды и от EAA",
            "Бета-аланин: покалывание — это эффект или побочка",
            "Кофеин как предтрен: реальная эффективная доза",
            "Омега-3 для восстановления: доказано или нет",
        ]
    },
    1: {
        "rubric": "Маркетинговая уловка под лупой",
        "format_hint": "разбор конкретного маркетингового приёма на упаковке/в рекламе спортпита по шаблону",
        "topics": [
            "'Proprietary blend' — почему это способ спрятать реальные дозировки",
            "'Клинически доказано' без ссылки на исследование — что это значит на деле",
            "Мега-дозировки витаминов в комплексах: польза или просто цифра на этикетке",
            "Фото 'до/после' в рекламе спортпита — как их подделывают",
            "Слово 'натуральный' на упаковке БАДа: юридически ничего не значит",
            "Скидочные коды у блогеров: как это влияет на объективность обзора",
        ]
    },
    2: {
        "rubric": "Сравнение форм и брендов",
        "format_hint": "сравнение разных форм одного вещества или подходов по шаблону, с акцентом на цена/качество",
        "topics": [
            "Креатин моногидрат vs HCl vs буферизованный — есть ли разница по исследованиям",
            "Сывороточный концентрат vs изолят vs гидролизат — за что переплата",
            "Растительный протеин (горох/рис) vs сывороточный — по аминокислотному профилю",
            "Магний: цитрат vs глицинат vs оксид — усвояемость и цена",
            "Капсулы vs порошок для одного и того же вещества — есть ли разница в эффекте",
        ]
    },
    3: {
        "rubric": "Разбор по запросу подписчиков",
        "format_hint": "разбор конкретного продукта или вещества, о котором чаще всего спрашивают, по шаблону",
        "topics": [
            "ZMA перед сном: работает на тестостерон или нет",
            "Глютамин для восстановления: есть ли смысл при обычном рационе",
            "L-карнитин для жиросжигания: что показывают исследования",
            "Трибулус террестрис как бустер тестостерона: разбор по фактам",
            "Цитруллин малат для пампа: доказанный эффект или ощущения",
        ]
    },
    4: {
        "rubric": "Коротко: работает / не работает",
        "format_hint": "сжатый вердикт-пост по спорной добавке, без длинного разбора, но с сохранением логики шаблона в 2-3 предложениях на пункт",
        "topics": [
            "HMB: стоит ли добавлять к протеину и креатину",
            "Ашваганда для снижения кортизола и роста силы: что говорят данные",
            "D-аспарагиновая кислота (DAA) как бустер тестостерона",
            "Жиросжигатели с 'термогенным эффектом': разбор состава",
            "Гейнеры: это удобство или просто дорогой сахар с белком",
        ]
    },
    5: {
        "rubric": "Рейтинг недели",
        "format_hint": "подборка 3-5 пунктов в формате мини-рейтинга (доказанно работает / спорно / маркетинг), каждый пункт с эмодзи-вердиктом",
        "topics": [
            "Топ-3 добавки с самой сильной доказательной базой",
            "3 популярные добавки, эффективность которых сильно преувеличена",
            "Антирейтинг маркетинговых формулировок на этикетках спортпита",
            "Что из 'must have' у новичков реально не нужно в первый год тренировок",
        ]
    },
    6: {
        "rubric": "Итоги недели",
        "format_hint": "короткое резюме недели: что разобрали, какой главный вывод, вопрос аудитории на подумать",
        "topics": [
            "Главный вывод недели одной фразой + что разобрали",
            "Какая добавка из недели удивила даже нас цифрами исследований",
            "Вопрос аудитории: что разобрать на следующей неделе",
        ]
    },
}

# =============================================================================
# УМНАЯ ОБРЕЗКА ТЕКСТА (с учётом HTML-тегов)
# =============================================================================
def strip_html_tags(html_text: str) -> str:
    """Удаляет HTML-теги и возвращает чистый текст для подсчёта видимых символов."""
    return re.sub(r'<[^>]+>', '', html_text)


def count_visible_chars(html_text: str) -> int:
    """Считает количество видимых символов (без HTML-тегов)."""
    return len(strip_html_tags(html_text))


def smart_truncate(html_text: str, max_visible: int = TELEGRAM_CAPTION_LIMIT) -> str:
    """
    Обрезает HTML-текст так, чтобы видимых символов было не больше max_visible.
    Не ломает HTML-теги, обрезает по целым словам, добавляет многоточие.
    """
    visible = strip_html_tags(html_text)
    if len(visible) <= max_visible:
        return html_text

    # Нужно обрезать. Ищем позицию в чистом тексте
    target_len = max_visible - 1  # место для многоточия

    # Строим карту: позиция в видимом тексте -> позиция в HTML
    visible_pos = 0
    html_pos = 0
    pos_map = {}  # visible_pos -> html_pos

    in_tag = False
    for i, ch in enumerate(html_text):
        if ch == '<':
            in_tag = True
        elif ch == '>':
            in_tag = False
            pos_map[visible_pos] = i + 1  # после закрывающей скобки
        elif not in_tag:
            pos_map[visible_pos] = i
            visible_pos += 1

    # Находим html-позицию, соответствующую target_len видимых символов
    if target_len not in pos_map:
        # Берём ближайшую меньшую
        available = [k for k in pos_map.keys() if k <= target_len]
        if not available:
            return html_text[:max_visible] + "…"
        target_len = max(available)

    cut_html_pos = pos_map[target_len]

    # Обрезаем HTML до этой позиции
    truncated = html_text[:cut_html_pos + 1]

    # Обрезаем по целому слову (ищем последний пробел)
    last_space = truncated.rfind(' ')
    if last_space > len(truncated) * 0.7:  # если нашли пробел не слишком близко к началу
        truncated = truncated[:last_space]

    # Закрываем все открытые теги
    truncated = close_open_tags(truncated)

    return truncated.rstrip() + "…"


def close_open_tags(html_text: str) -> str:
    """Закрывает все незакрытые HTML-теги в тексте."""
    # Находим все открывающие и закрывающие теги
    open_tags = re.findall(r'<(b|i|u|s|code|pre|a)[^>]*>', html_text)
    close_tags = re.findall(r'</(b|i|u|s|code|pre|a)>', html_text)

    # Считаем незакрытые
    tag_stack = []
    for tag in open_tags:
        tag_stack.append(tag)
    for tag in close_tags:
        if tag_stack and tag_stack[-1] == tag:
            tag_stack.pop()
        # если закрывающий тег без открывающего — игнорируем

    # Закрываем в обратном порядке
    for tag in reversed(tag_stack):
        html_text += f"</{tag}>"

    return html_text


# =============================================================================
# РАБОТА С ИСТОРИЕЙ
# =============================================================================
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"⚠️ Не удалось прочитать историю тем: {e}")
    return {}


def save_history(history):
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"⚠️ Не удалось сохранить историю тем: {e}")


def pick_topic(weekday: int) -> str:
    """Выбирает подтему для дня недели, избегая последних MEMORY_DEPTH повторов."""
    day_data = THEMES[weekday]
    pool = day_data["topics"]

    history = load_history()
    key = str(weekday)
    recent = history.get(key, [])

    candidates = [t for t in pool if t not in recent[-MEMORY_DEPTH:]]
    if not candidates:
        candidates = pool

    topic = random.choice(candidates)

    recent.append(topic)
    history[key] = recent[-MEMORY_DEPTH * 2:]
    save_history(history)

    return topic


def get_prompt_for_today():
    weekday = datetime.now().weekday()
    day_data = THEMES[weekday]
    topic = pick_topic(weekday)

    prompt = f"""Напиши пост для Telegram-канала "Спортпит без воды" — независимые разборы спортивного питания и БАДов на основе исследований, а не маркетинга бренда.

Рубрика дня: {day_data['rubric']}
Формат: {day_data['format_hint']}
Конкретная тема поста: {topic}

ОБЯЗАТЕЛЬНАЯ СТРУКТУРА ПОСТА:
1. <b>Состав</b> — что это за вещество/продукт, из чего состоит или что заявлено на этикетке.
2. 🔬 <b>Что говорит исследование</b> — краткий honest вывод по реальным данным. НИКОГДА не выдумывай конкретные названия исследований, авторов, журналы или цифры.
3. ⚠️ Если в теме есть маркетинговая уловка — обозначь её явно с этим эмодзи.
4. <b>Вердикт</b> — ✅ (работает) или ❌ (не работает), либо оба.
5. <b>Цена/качество</b> — короткий честный вывод.

КРИТИЧЕСКИ ВАЖНО:
- Общий объём видимого текста (БЕЗ учёта HTML-тегов <b></b>, <i></i>) — максимум 700 символов. Telegram даёт 1024 символа на caption к фото, но HTML-теги тоже считаются. Поэтому пиши КОРОТКО.
- Используй HTML-теги: <b>жирный</b>, <i>курсив</i>.
- Эмодзи строго: 🔬 — исследование, ⚠️ — уловка, ✅ — работает, ❌ — не работает.
- Источник (если точно знаешь) — ОДНОЙ строкой в конце: "Источник: ..."
- 1-2 хэштега в самом конце.
- Короткий вопрос аудитории в конце.
- ВЫДАВАЙ ТОЛЬКО ГОТОВЫЙ ТЕКСТ ПОСТА. Без комментариев, счётчиков, пояснений.
"""
    return prompt, topic, day_data


# =============================================================================
# GEMINI API — ГЕНЕРАЦИЯ ТЕКСТА
# =============================================================================
def get_available_models():
    """Получает список доступных моделей Gemini через API."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"

    try:
        response = requests.get(url, timeout=(5, 15))
        if response.status_code == 200:
            data = response.json()
            models = data.get("models", [])
            available = [
                m["name"].replace("models/", "")
                for m in models
                if "generateContent" in m.get("supportedGenerationMethods", [])
            ]
            logger.info(f"📋 Доступные модели Gemini: {', '.join(available[:10])}")
            return available
        return []
    except Exception as e:
        logger.warning(f"⚠️ Не удалось получить список моделей: {e}")
        return []


def call_gemini_text(model_name: str, prompt_text: str):
    """Запрашивает текст у Gemini. Возвращает текст или None."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 4000
        }
    }

    try:
        logger.info(f"⏳ Пробуем {model_name} для текста...")
        response = requests.post(url, json=payload, timeout=(10, 60))
        data = response.json()

        if response.status_code != 200:
            error_msg = json.dumps(data, ensure_ascii=False)[:400]
            logger.warning(f"⚠️ {model_name} HTTP {response.status_code}: {error_msg}")
            return None

        candidates = data.get("candidates", [])
        if not candidates:
            logger.warning(f"⚠️ {model_name}: пустой candidates")
            return None

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            logger.warning(f"⚠️ {model_name}: пустой parts")
            return None

        text = parts[0].get("text", "").strip()
        finish_reason = candidates[0].get("finishReason", "UNKNOWN")

        logger.info(f"📊 {model_name}: finishReason={finish_reason}, длина={len(text)}")

        if text and len(text) > 20:
            return text
        return None

    except Exception as e:
        logger.warning(f"⚠️ Ошибка {model_name}: {e}")
        return None


def generate_post():
    """Возвращает (текст_поста, тема, рубрика) или (None, None, None) при неудаче."""
    prompt_text, topic, day_data = get_prompt_for_today()

    for model in TEXT_MODELS:
        text = call_gemini_text(model, prompt_text)
        if text:
            visible_len = count_visible_chars(text)
            total_len = len(text)

            logger.info(f"📏 Сгенерировано: {visible_len} видимых / {total_len} всего символов")

            # Если видимых символов больше лимита — умно обрезаем
            if visible_len > TELEGRAM_CAPTION_LIMIT:
                logger.warning(f"⚠️ Текст слишком длинный ({visible_len} видимых симв.). Умная обрезка до {TELEGRAM_CAPTION_LIMIT}...")
                text = smart_truncate(text, TELEGRAM_CAPTION_LIMIT)
                visible_len = count_visible_chars(text)
                total_len = len(text)

            # Финальная проверка: всего символов (с HTML) не должно превышать 1024
            if total_len > 1024:
                logger.warning(f"⚠️ Всего символов с HTML = {total_len}, обрезаем до 1020...")
                text = smart_truncate(text, 1020 - (total_len - visible_len))
                visible_len = count_visible_chars(text)
                total_len = len(text)

            logger.info(f"✅ Текст готов: {visible_len} видимых / {total_len} всего символов")
            return text, topic, day_data["rubric"]

    logger.error("❌ Все текстовые модели вернули пустой/короткий текст")
    return None, None, None


# =============================================================================
# СЖАТИЕ ИЗОБРАЖЕНИЯ
# =============================================================================
def compress_image(image_bytes: bytes, max_width: int = 1280, quality: int = 82) -> bytes:
    try:
        img = Image.open(BytesIO(image_bytes))
        img = img.convert("RGB")

        if img.width > max_width:
            ratio = max_width / img.width
            new_size = (max_width, int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)

        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=quality, optimize=True)
        compressed = buffer.getvalue()

        logger.info(f"🗜️ Сжали картинку: {len(image_bytes)} → {len(compressed)} байт")
        return compressed
    except Exception as e:
        logger.warning(f"⚠️ Не удалось сжать изображение, отправляем как есть: {e}")
        return image_bytes


# =============================================================================
# UNSPLASH API — ПОЛУЧЕНИЕ РЕАЛЬНЫХ ФОТО
# =============================================================================
def generate_image(topic: str, rubric: str):
    """Получает качественное реальное фото с Unsplash по ключевым словам."""

    base_keywords = [
        "protein powder scoop",
        "supplement capsules pills",
        "supplement label ingredients",
        "protein shake",
        "vitamins bottle closeup",
        "lab research science",
        "creatine powder",
        "gym workout",
        "nutrition facts label",
        "fitness supplements flatlay"
    ]

    selected_keywords = random.sample(base_keywords, min(4, len(base_keywords)))
    query = urllib.parse.quote(" ".join(selected_keywords))

    url = f"https://api.unsplash.com/photos/random?query={query}&orientation=landscape&content_filter=high&w=1200&h=630&client_id={UNSPLASH_ACCESS_KEY}"

    headers = {"Accept-Version": "v1"}

    try:
        logger.info(f"⏳ Ищем фото на Unsplash: {query}...")
        response = requests.get(url, headers=headers, timeout=(5, 15))

        if response.status_code == 200:
            data = response.json()
            image_url = data.get("urls", {}).get("regular")
            download_url = data.get("urls", {}).get("full")

            final_url = download_url if download_url else image_url

            if final_url:
                img_response = requests.get(final_url, timeout=(5, 15))
                if img_response.status_code == 200 and len(img_response.content) > 1000:
                    photographer = data.get('user', {}).get('name', 'Unknown')
                    logger.info(f"✅ Фото найдено: {len(img_response.content)} байт (Автор: {photographer})")
                    return compress_image(img_response.content)
                else:
                    logger.warning("⚠️ Пустой ответ при скачивании изображения")
                    return None

        elif response.status_code == 401:
            logger.error("❌ Неверный UNSPLASH_ACCESS_KEY!")
            return None

        elif response.status_code == 404:
            logger.warning("⚠️ Unsplash не нашел фото. Пробуем fallback...")
            fallback_queries = ["protein", "gym", "fitness food", "workout"]
            for fallback_query in fallback_queries:
                fallback_url = f"https://api.unsplash.com/photos/random?query={fallback_query}&orientation=landscape&content_filter=high&w=1200&h=630&client_id={UNSPLASH_ACCESS_KEY}"
                try:
                    fallback_response = requests.get(fallback_url, headers=headers, timeout=(5, 15))
                    if fallback_response.status_code == 200:
                        data = fallback_response.json()
                        image_url = data.get("urls", {}).get("regular")
                        if image_url:
                            img_response = requests.get(image_url, timeout=(5, 15))
                            if img_response.status_code == 200 and len(img_response.content) > 1000:
                                photographer = data.get('user', {}).get('name', 'Unknown')
                                logger.info(f"✅ Фото найдено (fallback): {len(img_response.content)} байт")
                                return compress_image(img_response.content)
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка fallback '{fallback_query}': {e}")
                    continue
            logger.warning("⚠️ Все fallback запросы не дали результата")
            return None

        elif response.status_code == 429:
            logger.warning("⚠️ Превышен лимит запросов к Unsplash API")
            return None
        else:
            logger.warning(f"⚠️ Unsplash API error: HTTP {response.status_code}")
            return None

    except requests.exceptions.Timeout:
        logger.warning("⏱️ Превышено время ожидания Unsplash API")
        return None
    except Exception as e:
        logger.warning(f"⚠️ Ошибка загрузки фото с Unsplash: {e}")
        return None


# =============================================================================
# TELEGRAM — ПУБЛИКАЦИЯ
# =============================================================================
def publish_to_telegram(text):
    """Публикует обычное текстовое сообщение (fallback)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    try:
        response = requests.post(url, json=payload, timeout=(5, 30))
        data = response.json()

        if response.status_code == 200 and data.get("ok"):
            logger.info(f"✅ Пост опубликован (текстом)! Message ID: {data['result']['message_id']}")
            return True
        else:
            logger.error(f"❌ Ошибка Telegram: {data}")
            return False

    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return False


def publish_photo_to_telegram(image_bytes: bytes, text: str, max_attempts: int = 3):
    """Публикует фото вместе с текстом в качестве единой подписи (caption)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"

    # Финальная проверка перед отправкой
    if len(text) > 1024:
        logger.warning(f"⚠️ Финальная обрезка: {len(text)} → 1020 символов")
        text = smart_truncate(text, 1020)

    data = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "caption": text,
        "parse_mode": "HTML",
    }

    for attempt in range(1, max_attempts + 1):
        files = {"photo": ("cover.jpg", image_bytes, "image/jpeg")}
        try:
            logger.info(f"⏳ Отправка фото в Telegram, попытка {attempt}/{max_attempts}...")
            response = requests.post(url, data=data, files=files, timeout=(15, 180))
            resp_json = response.json()

            if response.status_code == 200 and resp_json.get("ok"):
                logger.info(f"✅ Пост опубликован! Message ID: {resp_json['result']['message_id']}")
                return True
            else:
                # Если ошибка из-за длины caption — обрезаем и пробуем ещё
                error_desc = resp_json.get("description", "")
                if "caption" in error_desc.lower() or "too long" in error_desc.lower() or "message is too long" in error_desc.lower():
                    logger.warning(f"⚠️ Telegram отказал: caption слишком длинный. Обрезаем...")
                    text = smart_truncate(text, 900)
                    data["caption"] = text
                    continue
                logger.error(f"❌ Ошибка Telegram: {resp_json}")
                return False

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            logger.warning(f"⚠️ Сетевая ошибка (попытка {attempt}/{max_attempts}): {e}")
            if attempt < max_attempts:
                time.sleep(5 * attempt)
                continue
            logger.error("❌ Не удалось отправить фото после всех попыток")
            return False
        except Exception as e:
            logger.error(f"❌ Ошибка отправки фото: {e}")
            return False

    return False


# =============================================================================
# ГЛАВНЫЙ ЦИКЛ
# =============================================================================
def main():
    logger.info("🚀 Запуск автопостинга (Спортпит без воды)...")

    available = get_available_models()
    if available:
        logger.info(f"📋 Найдено {len(available)} доступных моделей Gemini")

    post_text, topic, rubric = generate_post()
    if not post_text:
        logger.error("❌ Не удалось сгенерировать текст поста. Завершение.")
        sys.exit(1)

    image_bytes = generate_image(topic, rubric)

    if image_bytes:
        success = publish_photo_to_telegram(image_bytes, post_text)
    else:
        logger.warning("⚠️ Картинка не получена — публикуем только текст (fallback)")
        success = publish_to_telegram(post_text)

    if not success:
        logger.error("❌ Не удалось опубликовать пост. Завершение.")
        sys.exit(1)

    logger.info("🎉 Готово! Пост успешно опубликован.")


if __name__ == "__main__":
    main()
