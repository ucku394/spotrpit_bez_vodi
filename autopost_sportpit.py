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
MEMORY_DEPTH = 4

# Реальный технический лимит caption в Telegram — 1024 (в UTF-16 code units).
TELEGRAM_HARD_LIMIT = 1024
# Целевой бюджет, в который стараемся уложиться при обрезке (запас под теги/погрешности).
TELEGRAM_VISIBLE_LIMIT = 950

MIN_POST_LENGTH = 400   # Если короче — отклоняем и генерируем заново
MAX_POST_LENGTH = 950   # Если сильно длиннее — тоже отклоняем и генерируем заново,
                         # а не калечим текст жёсткой обрезкой

# ВАЖНО: используем основы слов, а не точные словоформы,
# т.к. в промпте раздел называется "Что говорят исследования" (не "исследование")
REQUIRED_SECTIONS = ['Состав', 'исследован', 'Вердикт', 'Цена/качество']

# АКТУАЛЬНЫЕ МОДЕЛИ GEMINI
TEXT_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
]

# =============================================================================
# ТЕМЫ ПО ДНЯМ НЕДЕЛИ
# =============================================================================
THEMES = {
    0: {
        "rubric": "Разбор добавки",
        "format_hint": "полный независимый разбор одной конкретной добавки/вещества",
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
        "format_hint": "разбор конкретного маркетингового приёма на упаковке/в рекламе",
        "topics": [
            "'Proprietary blend' — почему это способ спрятать реальные дозировки",
            "'Клинически доказано' без ссылки на исследование — что это значит",
            "Мега-дозировки витаминов в комплексах: польза или цифра на этикетке",
            "Фото 'до/после' в рекламе спортпита — как их подделывают",
            "Слово 'натуральный' на упаковке БАДа: юридически ничего не значит",
            "Скидочные коды у блогеров: как это влияет на объективность",
        ]
    },
    2: {
        "rubric": "Сравнение форм и брендов",
        "format_hint": "сравнение разных форм одного вещества или подходов, акцент на цена/качество",
        "topics": [
            "Креатин моногидрат vs HCl vs буферизованный — есть ли разница",
            "Сывороточный концентрат vs изолят vs гидролизат — за что переплата",
            "Растительный протеин (горох/рис) vs сывороточный — по аминокислотам",
            "Магний: цитрат vs глицинат vs оксид — усвояемость и цена",
            "Капсулы vs порошок для одного и того же вещества — есть ли разница",
        ]
    },
    3: {
        "rubric": "Разбор по запросу подписчиков",
        "format_hint": "разбор конкретного продукта или вещества, о котором часто спрашивают",
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
        "format_hint": "сжатый вердикт-пост по спорной добавке, без длинного разбора",
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
        "format_hint": "подборка 3-х пунктов в формате мини-рейтинга с эмодзи-вердиктом",
        "topics": [
            "Топ-3 добавки с самой сильной доказательной базой",
            "3 популярные добавки, эффективность которых сильно преувеличена",
            "Антирейтинг маркетинговых формулировок на этикетках спортпита",
            "Что из 'must have' у новичков реально не нужно в первый год",
        ]
    },
    6: {
        "rubric": "Итоги недели",
        "format_hint": "короткое резюме недели: что разобрали, главный вывод, вопрос аудитории",
        "topics": [
            "Главный вывод недели одной фразой + что разобрали",
            "Какая добавка из недели удивила даже нас цифрами исследований",
            "Вопрос аудитории: что разобрать на следующей неделе",
        ]
    },
}

# =============================================================================
# РАБОТА С HTML И ОБРЕЗКА
# =============================================================================
SECTION_SEPARATOR = '\n\n'

def strip_html_tags(html_text: str) -> str:
    return re.sub(r'<[^>]+>', '', html_text)

def utf16_len(s: str) -> int:
    """
    Длина строки в UTF-16 code units — именно так Telegram считает
    лимит caption/text (эмодзи вне BMP занимают 2 юнита).
    """
    return len(s.encode('utf-16-le')) // 2

def count_visible_chars(html_text: str) -> int:
    return utf16_len(strip_html_tags(html_text))

def close_open_tags(html_text: str) -> str:
    open_tags = re.findall(r'<(b|i|u|s|code|pre)(?:\s[^>]*)?>', html_text)
    close_tags = re.findall(r'</(b|i|u|s|code|pre)>', html_text)

    tag_count = {}
    for tag in open_tags:
        tag_count[tag] = tag_count.get(tag, 0) + 1
    for tag in close_tags:
        tag_count[tag] = tag_count.get(tag, 0) - 1

    tags_to_close = []
    for tag in reversed(open_tags):
        if tag_count.get(tag, 0) > 0:
            tags_to_close.append(tag)
            tag_count[tag] -= 1

    for tag in tags_to_close:
        html_text += f"</{tag}>"

    return html_text

def _hard_char_trim(html_text: str, limit: int) -> str:
    """Крайний случай: посимвольная обрезка с сохранением тегов целиком."""
    result = []
    current_visible = 0
    i = 0
    n = len(html_text)
    while i < n and current_visible < limit:
        if html_text[i] == '<':
            end = html_text.find('>', i)
            if end == -1:
                break
            result.append(html_text[i:end + 1])
            i = end + 1
        else:
            ch = html_text[i]
            ch_len = utf16_len(ch)
            if current_visible + ch_len > limit:
                break
            result.append(ch)
            current_visible += ch_len
            i += 1
    return ''.join(result).rstrip()

def _trim_to_last_sentence(text: str, limit: int) -> str:
    """
    Обрезает текст по видимой длине до последнего ЗАВЕРШЁННОГО предложения
    (заканчивающегося на . ! ? …), не превышая limit. Если ни одного полного
    предложения не влезает — крайний случай: жёсткая посимвольная обрезка.
    """
    if count_visible_chars(text) <= limit:
        return text.rstrip()

    visible_acc = 0
    i = 0
    n = len(text)
    last_good_end = 0

    while i < n:
        ch = text[i]
        if ch == '<':
            end = text.find('>', i)
            if end == -1:
                break
            i = end + 1
            continue

        visible_acc += utf16_len(ch)
        i += 1

        if visible_acc > limit:
            break

        if ch in '.!?…' and (i >= n or text[i] in ' \n'):
            last_good_end = i

    if last_good_end > 0:
        return text[:last_good_end].rstrip()

    return _hard_char_trim(text, limit)

def ensure_caption_length(html_text: str) -> str:
    """
    Подгоняет пост под лимит Telegram, стараясь сохранить ЦЕЛЫЕ смысловые
    блоки (разделы поста, разделённые пустой строкой) и никогда не обрывать
    текст посреди предложения.
    """
    visible_len = count_visible_chars(html_text)
    if visible_len <= TELEGRAM_VISIBLE_LIMIT:
        return close_open_tags(html_text)

    logger.warning(f"⚠️ Текст превышает лимит (Видимых: {visible_len}, лимит {TELEGRAM_VISIBLE_LIMIT}). Обрезаем по разделам...")

    sections = html_text.split(SECTION_SEPARATOR)
    kept = []
    current_visible = 0

    for section in sections:
        section_visible = count_visible_chars(section)
        extra = section_visible + (2 if kept else 0)
        if current_visible + extra <= TELEGRAM_VISIBLE_LIMIT:
            kept.append(section)
            current_visible += extra
        else:
            break

    if kept:
        result = SECTION_SEPARATOR.join(kept).rstrip()
        logger.info(f"✂️ Оставили {len(kept)} из {len(sections)} разделов поста, текст завершён логически.")
        return close_open_tags(result)

    trimmed = _trim_to_last_sentence(sections[0], TELEGRAM_VISIBLE_LIMIT)
    return close_open_tags(trimmed)


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
    """
    ВАЖНО: промпт собирается через список строк и join('\n'), а не через
    один большой f-string с тройными кавычками. Это исключает класс ошибок
    SyntaxError: unterminated triple-quoted string literal, который возникает,
    если внутри текста промпта случайно образуется последовательность из
    трёх кавычек подряд (например, при копировании текста с "умными" кавычками
    или редактировании рядом с закрывающей кавычкой фразы).
    """
    weekday = datetime.now().weekday()
    day_data = THEMES[weekday]
    topic = pick_topic(weekday)

    lines = [
        'Ты — эксперт по спортивному питанию. Напиши пост для Telegram-канала «Спортпит без воды».',
        '',
        f'РУБРИКА: {day_data["rubric"]}',
        f'ТЕМА: {topic}',
        '',
        'СТРУКТУРА ПОСТА (ОБЯЗАТЕЛЬНО выполни ВСЕ 7 пунктов, каждый ёмко и по делу):',
        '',
        '1️⃣ <b>Состав</b> — что это за вещество/продукт, из чего состоит, основные компоненты (1-2 предложения)',
        '',
        '2️⃣ 🔬 <b>Что говорят исследования</b> — реальные научные данные об эффективности (2-3 предложения)',
        '',
        '3️⃣ ⚠️ <b>Маркетинговая уловка</b> — что обещают производители vs реальность (1-2 предложения). Если продукт честный — напиши: Честный продукт без скрытых уловок',
        '',
        '4️⃣ <b>Вердикт</b> — работает / не работает / спорно (1 предложение с объяснением)',
        '',
        '5️⃣ <b>Цена/качество</b> — стоит ли покупать (1 предложение)',
        '',
        '6️⃣ <b>Вопрос аудитории</b> — короткий вопрос подписчикам (5-10 слов)',
        '',
        '7️⃣ Хэштеги — 2 релевантных хэштега',
        '',
        'КРИТИЧЕСКИ ВАЖНО ПРО ОБЪЁМ (это жёсткое ограничение Telegram, а не пожелание):',
        '- Общий объём ВСЕГО поста — СТРОГО от 500 до 700 видимых символов (без учёта HTML-тегов). Считай сам перед выдачей ответа.',
        '- Если чувствуешь, что текст получается длиннее — сокращай формулировки, а не убирай пункты.',
        '- НЕ пиши развёрнуто и не растягивай предложения — пиши предельно ёмко.',
        '- Каждый пункт с новой строки, между пунктами пустая строка.',
        '- Используй теги <b>жирный</b> для заголовков пунктов.',
        '- НЕ выдумывай названия исследований, авторов, журналов.',
        '- Не используй символ кавычек внутри текста поста.',
        '- Выдай ТОЛЬКО готовый пост, без вступлений.',
        '',
        'ВАЖНО: Пост должен быть ПОЛНОСТЬЮ завершён, включая все 7 пунктов структуры, и укладываться в 500-700 символов!',
    ]

    prompt = '\n'.join(lines)
    return prompt, topic, day_data


# =============================================================================
# GEMINI API
# =============================================================================
def validate_post_structure(text: str) -> tuple:
    """Проверяет, содержит ли пост все обязательные разделы (по основе слова)."""
    text_lower = text.lower()
    missing = []

    for section in REQUIRED_SECTIONS:
        if section.lower() not in text_lower:
            missing.append(section)

    return len(missing) == 0, missing

def call_gemini_text(model_name: str, prompt_text: str):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 2048,
            "topP": 0.95,
        }
    }

    try:
        logger.info(f"⏳ Генерация текста через {model_name}...")
        response = requests.post(url, json=payload, timeout=(10, 120))
        data = response.json()

        if response.status_code != 200:
            error_msg = str(data)[:300]
            logger.warning(f"⚠️ {model_name} HTTP {response.status_code}: {error_msg}")
            return None

        candidates = data.get("candidates", [])
        if not candidates:
            logger.warning(f"⚠️ {model_name}: пустые candidates")
            return None

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            logger.warning(f"⚠️ {model_name}: пустые parts")
            return None

        text = parts[0].get("text", "").strip()

        text = re.sub(r'^(Вот ваш пост:|Конечно, вот пост:|Разбор темы:|Пост для канала:)\s*\n?', '', text, flags=re.IGNORECASE)
        text = re.sub(r'^```\s*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)

        visible_len = count_visible_chars(text)

        if visible_len < MIN_POST_LENGTH:
            logger.warning(f"⚠️ {model_name}: текст слишком короткий ({visible_len} символов, минимум {MIN_POST_LENGTH})")
            return None

        if visible_len > MAX_POST_LENGTH:
            logger.warning(f"⚠️ {model_name}: текст слишком длинный ({visible_len} символов, максимум {MAX_POST_LENGTH}), пробуем ещё раз")
            return None

        is_valid, missing = validate_post_structure(text)
        if not is_valid:
            logger.warning(f"⚠️ {model_name}: не хватает разделов: {', '.join(missing)}")
            return None

        logger.info(f"✅ {model_name}: сгенерировано {visible_len} видимых символов, все разделы на месте")
        return text

    except Exception as e:
        logger.warning(f"⚠️ Ошибка {model_name}: {e}")
        return None

def generate_post():
    """Генерирует пост с проверкой качества, полноты и объёма."""
    prompt_text, topic, day_data = get_prompt_for_today()

    for attempt in range(10):
        for model in TEXT_MODELS:
            text = call_gemini_text(model, prompt_text)
            if text:
                final_text = ensure_caption_length(text)
                visible_len = count_visible_chars(final_text)
                total_len = len(final_text)

                logger.info(f"✅ Текст готов: {visible_len} видимых / {total_len} всего символов")
                return final_text, topic, day_data["rubric"]

        logger.warning(f"⚠️ Попытка {attempt + 1} не удалась, ждём 2 секунды...")
        time.sleep(2)

    logger.error("❌ Все попытки генерации поста провалены")
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
        logger.warning(f"️ Не удалось сжать изображение: {e}")
        return image_bytes


# =============================================================================
# UNSPLASH API
# =============================================================================
def generate_image(topic: str, rubric: str):
    base_keywords = [
        "protein powder scoop", "supplement capsules pills", "supplement label ingredients",
        "protein shake", "vitamins bottle closeup", "lab research science",
        "creatine powder", "gym workout", "nutrition facts label", "fitness supplements flatlay"
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
            final_url = data.get("urls", {}).get("full") or data.get("urls", {}).get("regular")

            if final_url:
                img_response = requests.get(final_url, timeout=(5, 15))
                if img_response.status_code == 200 and len(img_response.content) > 1000:
                    photographer = data.get('user', {}).get('name', 'Unknown')
                    logger.info(f"✅ Фото найдено: {len(img_response.content)} байт (Автор: {photographer})")
                    return compress_image(img_response.content)
        elif response.status_code == 401:
            logger.error("❌ Неверный UNSPLASH_ACCESS_KEY!")
            return None
        elif response.status_code == 404:
            fallback_queries = ["protein", "gym", "fitness food", "workout"]
            for fq in fallback_queries:
                try:
                    fb_url = f"https://api.unsplash.com/photos/random?query={fq}&orientation=landscape&content_filter=high&w=1200&h=630&client_id={UNSPLASH_ACCESS_KEY}"
                    fb_resp = requests.get(fb_url, headers=headers, timeout=(5, 15))
                    if fb_resp.status_code == 200:
                        data = fb_resp.json()
                        img_url = data.get("urls", {}).get("regular")
                        if img_url:
                            img_response = requests.get(img_url, timeout=(5, 15))
                            if img_response.status_code == 200 and len(img_response.content) > 1000:
                                logger.info(f"✅ Фото найдено (fallback)")
                                return compress_image(img_response.content)
                except Exception:
                    continue
        elif response.status_code == 429:
            logger.warning("⚠️ Превышен лимит запросов к Unsplash API")

        return None
    except Exception as e:
        logger.warning(f"⚠️ Ошибка загрузки фото с Unsplash: {e}")
        return None


# =============================================================================
# TELEGRAM — ПУБЛИКАЦИЯ
# =============================================================================
def publish_to_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    if count_visible_chars(text) > TELEGRAM_HARD_LIMIT:
        text = ensure_caption_length(text)

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
            logger.error(f"❌ Ошибка Telegram (текст): {data}")
            return False
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return False

def publish_photo_to_telegram(image_bytes: bytes, text: str, max_attempts: int = 3):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"

    text = close_open_tags(text)
    if count_visible_chars(text) > TELEGRAM_HARD_LIMIT:
        logger.warning("⚠️ АВАРИЙНАЯ ОБРЕЗКА: caption превышает лимит Telegram!")
        text = ensure_caption_length(text)

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
                logger.info(f"✅ Пост опубликован с фото! Message ID: {resp_json['result']['message_id']}")
                return True
            else:
                error_desc = resp_json.get("description", "")
                if "can't parse entities" in error_desc.lower() or "tag" in error_desc.lower():
                    logger.warning("⚠️ Ошибка парсинга HTML. Исправляем теги...")
                    text_plain = strip_html_tags(text)
                    data["caption"] = text_plain
                    data["parse_mode"] = None
                    response = requests.post(url, data=data, files=files, timeout=(15, 180))
                    resp_json = response.json()
                    if response.status_code == 200 and resp_json.get("ok"):
                        logger.info(f"✅ Пост опубликован (без HTML)! Message ID: {resp_json['result']['message_id']}")
                        return True

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

    post_text, topic, rubric = generate_post()
    if not post_text:
        logger.error("❌ Не удалось сгенерировать текст поста. Завершение.")
        sys.exit(1)

    logger.info(f"📝 ФИНАЛЬНЫЙ ТЕКСТ ({len(post_text)} всего / {count_visible_chars(post_text)} видимых):")
    logger.info("-" * 40)
    logger.info(post_text)
    logger.info("-" * 40)

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