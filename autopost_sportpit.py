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
# КОНФИГУРАЦИЯ — ДВИЖОК РАЗНООБРАЗНОГО КОНТЕНТА
# =============================================================================
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'topics_history.json')

TELEGRAM_HARD_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1024
TELEGRAM_SAFE_CAPTION_LIMIT = 960

MIN_POST_LENGTH = 520
MAX_POST_LENGTH = 2200

TEXT_MODELS = ["gemini-3.6-flash", "gemini-3.5-flash"]

FORMATS = [
    ("MYTH", "МИФ / ФАКТ", True, 14),
    ("BATTLE", "БИТВА ФОРМ", True, 13),
    ("LABEL", "ЭТИКЕТКА ПОД ЛУПОЙ", True, 12),
    ("MONEY", "ДЕНЬГИ НЕ ЛИШНИЕ", False, 10),
    ("QUICK", "30 СЕКУНД", False, 12),
    ("CASE", "РАЗБОР СИТУАЦИИ", False, 10),
    ("TRAP", "ЛОВУШКА МАРКЕТИНГА", True, 10),
    ("RANK", "ТОП / АНТИТОП", False, 8),
    ("QUESTION", "ВОПРОС ЗАЛУ", False, 6),
    ("WEEKEND", "ИТОГ БЕЗ ВОДЫ", False, 5),
]

TOPIC_BANK = [
    "Креатин моногидрат: работает или маркетинг",
    "Сывороточный протеин: когда он реально нужен",
    "BCAA против EAA и полноценного белка",
    "Бета-аланин: покалывание и реальный эффект",
    "Кофеин: рабочая доза без магии",
    "Омега-3: что реально можно ждать от добавки",
    "Мега-дозировки витаминов: польза или цифра на этикетке",
    "Proprietary blend: что скрывается за красивым названием",
    "Клинически доказано: что на самом деле означает эта фраза",
    "Фото до/после в рекламе спортпита",
    "Слово натуральный на упаковке",
    "Скидочные коды блогеров и объективность рекомендаций",
    "Креатин моногидрат против HCl",
    "Концентрат против изолята против гидролизата",
    "Растительный протеин против сывороточного",
    "Магний: цитрат, глицинат или оксид",
    "Капсулы против порошка: есть ли разница",
    "ZMA перед сном",
    "Глютамин для восстановления",
    "L-карнитин и жиросжигание",
    "Трибулус и тестостерон",
    "Цитруллин и памп",
    "HMB для набора и сохранения мышц",
    "Ашваганда и силовые показатели",
    "DAA как бустер тестостерона",
    "Жиросжигатели с термогенным эффектом",
    "Гейнер: удобство или дорогой способ добрать калории",
    "Предтрен: что действительно работает",
    "Электролиты: кому они нужны",
    "Коллаген для спортсмена",
    "Мелатонин и восстановление",
    "Витамин D без дефицита",
    "Цинк и тестостерон при нормальном питании",
    "Протеиновый батончик против обычного перекуса",
    "Порошковый протеин против готового напитка",
    "Дорогой креатин против обычного моногидрата",
    "Дорогой протеин против базового whey",
]

WEEKDAY_BIAS = {
    0: ["MYTH", "QUICK", "LABEL"],
    1: ["LABEL", "TRAP", "MONEY"],
    2: ["BATTLE", "MONEY", "MYTH"],
    3: ["CASE", "QUICK", "QUESTION"],
    4: ["TRAP", "RANK", "MYTH"],
    5: ["RANK", "BATTLE", "CASE"],
    6: ["WEEKEND", "QUESTION", "RANK"],
}

HASHTAGS = ["#спортпит", "#креатин", "#протеин", "#добавки", "#фитнес", "#питание", "#безводы", "#разбор"]

# =============================================================================
# ТЕМЫ ПО ДНЯМ НЕДЕЛИ
# =============================================================================
THEMES = {
    0: {
        "rubric": "Разбор добавки",
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
        "topics": [
            "'Proprietary blend' — почему это способ спрятать дозировки",
            "'Клинически доказано' без ссылки — что это значит",
            "Мега-дозировки витаминов: польза или цифра на этикетке",
            "Фото 'до/после' в рекламе — как их подделывают",
            "Слово 'натуральный' на упаковке БАДа: юридически ничего не значит",
            "Скидочные коды у блогеров: влияние на объективность",
        ]
    },
    2: {
        "rubric": "Сравнение форм и брендов",
        "topics": [
            "Креатин моногидрат vs HCl vs буферизованный",
            "Сывороточный концентрат vs изолят vs гидролизат",
            "Растительный протеин (горох/рис) vs сывороточный",
            "Магний: цитрат vs глицинат vs оксид",
            "Капсулы vs порошок — есть ли разница в эффекте",
        ]
    },
    3: {
        "rubric": "Разбор по запросу подписчиков",
        "topics": [
            "ZMA перед сном: работает на тестостерон или нет",
            "Глютамин для восстановления: есть ли смысл",
            "L-карнитин для жиросжигания: что показывают исследования",
            "Трибулус террестрис как бустер тестостерона",
            "Цитруллин малат для пампа: доказанный эффект или ощущения",
        ]
    },
    4: {
        "rubric": "Коротко: работает / не работает",
        "topics": [
            "HMB: стоит ли добавлять к протеину и креатину",
            "Ашваганда для снижения кортизола и роста силы",
            "D-аспарагиновая кислота (DAA) как бустер тестостерона",
            "Жиросжигатели с 'термогенным эффектом'",
            "Гейнеры: удобство или дорогой сахар с белком",
        ]
    },
    5: {
        "rubric": "Рейтинг недели",
        "topics": [
            "Топ-3 добавки с самой сильной доказательной базой",
            "3 популярные добавки, эффективность которых преувеличена",
            "Антирейтинг маркетинговых формулировок на этикетках",
            "Что из 'must have' у новичков не нужно в первый год",
        ]
    },
    6: {
        "rubric": "Итоги недели",
        "topics": [
            "Главный вывод недели одной фразой",
            "Какая добавка удивила цифрами исследований",
            "Вопрос аудитории: что разобрать на следующей неделе",
        ]
    },
}

# =============================================================================
# УТИЛИТЫ ДЛЯ РАБОТЫ С ТЕКСТОМ
# =============================================================================
def strip_html_tags(html_text: str) -> str:
    return re.sub(r'<[^>]+>', '', html_text)

def utf16_len(s: str) -> int:
    """Длина в UTF-16 code units — так Telegram считает лимит."""
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

def smart_truncate(html_text: str, limit: int) -> str:
    """
    Обрезает текст до limit видимых символов, не ломая HTML.
    Старается закончить на завершённом предложении.
    """
    if count_visible_chars(html_text) <= limit:
        return close_open_tags(html_text)

    visible_acc = 0
    last_good_end = 0
    i = 0
    n = len(html_text)

    while i < n:
        if html_text[i] == '<':
            end = html_text.find('>', i)
            if end == -1:
                break
            i = end + 1
            continue

        ch = html_text[i]
        visible_acc += utf16_len(ch)
        i += 1

        if visible_acc > limit - 1:
            break

        if ch in '.!?…' and (i >= n or text[i] in ' \n'):
            last_good_end = i

    if last_good_end > 0:
        return close_open_tags(html_text[:last_good_end].rstrip()) + "…"

    # Жёсткая обрезка
    result = []
    current_visible = 0
    i = 0
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

    return close_open_tags(''.join(result).rstrip()) + "…"


# =============================================================================
# РАБОТА С ИСТОРИЕЙ
# =============================================================================
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"⚠️ Не удалось прочитать историю: {e}")
    return {}

def save_history(history):
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"⚠️ Не удалось сохранить историю: {e}")

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


# =============================================================================
# ПРОМПТ — НОВАЯ СТРУКТУРА ПОСТА
# =============================================================================
def get_prompt_for_today():
    weekday = datetime.now().weekday()
    day_data = THEMES[weekday]
    topic = pick_topic(weekday)

    lines = [
        'Ты — независимый эксперт по спортивному питанию. Пишешь для Telegram-канала «Спортпит без воды».',
        'Стиль: честный, без воды, без спонсорского вранья. Только факты и исследования.',
        '',
        f'Рубрика: {day_data["rubric"]}',
        f'Тема: {topic}',
        '',
        '=== СТРУКТУРА ПОСТА (строго соблюдай) ===',
        '',
        'Формат — НЕ список, а связный текст с визуальными разделителями:',
        '',
        '<b>НАЗВАНИЕ ДОБАВКИ/ТЕМЫ</b> (крупный заголовок, жирный)',
        '',
        '• <b>Состав</b> — 1-2 коротких предложения, что это и из чего состоит.',
        '',
        '• 🔬 <b>Что говорят исследования</b> — 2-3 предложения с выводами из реальных данных. НЕ выдумывай названия исследований и авторов.',
        '',
        '• ⚠️ <b>Маркетинговая уловка</b> — 1 предложение, что обещают vs реальность. Если честный продукт — напиши: «Честный продукт, уловок нет».',
        '',
        '• <b>Вердикт</b> — ✅ Работает / ❌ Не работает / ⚠️ Спорно + 1 предложение почему.',
        '',
        '• <b>Цена/качество</b> — 1 предложение: стоит ли переплачивать, что покупать.',
        '',
        '• <b>Вопрос аудитории</b> — 1 короткое предложение с вопросом подписчикам.',
        '',
        '#хэштег1 #хэштег2 (2 релевантных хэштега в конце)',
        '',
        '=== ПРАВИЛА ОФОРМЛЕНИЯ ===',
        '',
        '- Используй HTML-теги: <b>жирный</b> для заголовков и ключевых слов.',
        '- Между разделами — пустая строка (для визуального воздуха).',
        '- НЕ используй нумерацию 1️⃣ 2️⃣ 3️⃣ — только буллеты • или просто жирные заголовки.',
        '- НЕ пиши «Вот пост:» или другие вступления — сразу заголовок.',
        '- НЕ используй кавычки " внутри текста.',
        '- Общий объём: 450-650 ВИДИМЫХ символов (без HTML-тегов). Это жёсткий лимит Telegram.',
        '- Пиши ёмко, как ноты. Каждое слово на вес золота.',
        '',
        'Выдай ТОЛЬКО готовый текст поста.',
    ]

    prompt = '\n'.join(lines)
    return prompt, topic, day_data


# =============================================================================
# GEMINI API
# =============================================================================
def validate_post(text: str) -> tuple:
    text_lower = text.lower()
    missing = [el for el in REQUIRED_ELEMENTS if el.lower() not in text_lower]
    return len(missing) == 0, missing

def call_gemini_text(model_name: str, prompt_text: str):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {
            "temperature": 0.65,
            "maxOutputTokens": 2048,
            "topP": 0.95,
        }
    }

    try:
        logger.info(f"⏳ Генерация через {model_name}...")
        response = requests.post(url, json=payload, timeout=(10, 120))
        data = response.json()

        if response.status_code != 200:
            logger.warning(f"⚠️ {model_name} HTTP {response.status_code}: {str(data)[:300]}")
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

        # Чистим вступления
        text = re.sub(r'^(Вот ваш пост:|Конечно, вот пост:|Разбор темы:|Пост для канала:|Вот пост:)\s*\n?', '', text, flags=re.IGNORECASE)
        text = re.sub(r'^```\s*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)

        visible_len = count_visible_chars(text)

        if visible_len < MIN_POST_LENGTH:
            logger.warning(f"⚠️ {model_name}: слишком короткий ({visible_len} < {MIN_POST_LENGTH})")
            return None

        if visible_len > MAX_POST_LENGTH:
            logger.warning(f"⚠️ {model_name}: слишком длинный ({visible_len} > {MAX_POST_LENGTH})")
            return None

        is_valid, missing = validate_post(text)
        if not is_valid:
            logger.warning(f"⚠️ {model_name}: не хватает: {', '.join(missing)}")
            return None

        logger.info(f"✅ {model_name}: {visible_len} символов, структура ок")
        return text

    except Exception as e:
        logger.warning(f"⚠️ Ошибка {model_name}: {e}")
        return None

def generate_post():
    prompt_text, topic, day_data = get_prompt_for_today()

    for attempt in range(10):
        for model in TEXT_MODELS:
            text = call_gemini_text(model, prompt_text)
            if text:
                # Проверяем финальную длину
                if count_visible_chars(text) > TELEGRAM_SAFE_LIMIT:
                    logger.warning(f"⚠️ Обрезка до {TELEGRAM_SAFE_LIMIT} символов...")
                    text = smart_truncate(text, TELEGRAM_SAFE_LIMIT)

                visible_len = count_visible_chars(text)
                total_len = len(text)
                logger.info(f"✅ Пост готов: {visible_len} видимых / {total_len} всего символов")
                return text, topic, day_data["rubric"]

        logger.warning(f"⚠️ Попытка {attempt + 1} не удалась, ждём...")
        time.sleep(2)

    logger.error("❌ Все попытки провалены")
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

        logger.info(f"🗜️ Сжали: {len(image_bytes)} → {len(compressed)} байт")
        return compressed
    except Exception as e:
        logger.warning(f"⚠️ Не удалось сжать: {e}")
        return image_bytes


# =============================================================================
# UNSPLASH API
# =============================================================================
def generate_image(topic: str, rubric: str):
    base_keywords = [
        "protein powder scoop", "supplement capsules pills", "supplement label",
        "protein shake", "vitamins bottle", "lab research", "creatine powder",
        "gym workout", "nutrition label", "fitness supplements"
    ]
    selected = random.sample(base_keywords, min(3, len(base_keywords)))
    query = urllib.parse.quote(" ".join(selected))

    url = f"https://api.unsplash.com/photos/random?query={query}&orientation=landscape&content_filter=high&w=1200&h=630&client_id={UNSPLASH_ACCESS_KEY}"
    headers = {"Accept-Version": "v1"}

    try:
        logger.info(f"⏳ Ищем фото: {query}...")
        response = requests.get(url, headers=headers, timeout=(5, 15))

        if response.status_code == 200:
            data = response.json()
            final_url = data.get("urls", {}).get("full") or data.get("urls", {}).get("regular")
            if final_url:
                img_resp = requests.get(final_url, timeout=(5, 15))
                if img_resp.status_code == 200 and len(img_resp.content) > 1000:
                    logger.info(f"✅ Фото: {len(img_resp.content)} байт")
                    return compress_image(img_resp.content)

        elif response.status_code == 401:
            logger.error("❌ Неверный UNSPLASH_ACCESS_KEY!")
        elif response.status_code == 404:
            for fq in ["protein", "gym", "fitness"]:
                try:
                    fb_url = f"https://api.unsplash.com/photos/random?query={fq}&orientation=landscape&content_filter=high&w=1200&h=630&client_id={UNSPLASH_ACCESS_KEY}"
                    fb_resp = requests.get(fb_url, headers=headers, timeout=(5, 15))
                    if fb_resp.status_code == 200:
                        data = fb_resp.json()
                        img_url = data.get("urls", {}).get("regular")
                        if img_url:
                            img_resp = requests.get(img_url, timeout=(5, 15))
                            if img_resp.status_code == 200 and len(img_resp.content) > 1000:
                                return compress_image(img_resp.content)
                except Exception:
                    continue
        elif response.status_code == 429:
            logger.warning("⚠️ Лимит Unsplash")

        return None
    except Exception as e:
        logger.warning(f"⚠️ Ошибка Unsplash: {e}")
        return None


# =============================================================================
# TELEGRAM — ПУБЛИКАЦИЯ
# =============================================================================
def publish_to_telegram(text: str) -> bool:
    if count_visible_chars(text) > TELEGRAM_HARD_LIMIT:
        text = smart_truncate(text, TELEGRAM_HARD_LIMIT)

    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json=payload, timeout=(5, 30)
        )
        data = response.json()
        if response.status_code == 200 and data.get("ok"):
            logger.info(f"✅ Текстовый пост! ID: {data['result']['message_id']}")
            return True
        logger.error(f"❌ Ошибка: {data}")
        return False
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return False

def publish_photo_to_telegram(image_bytes: bytes, text: str, max_attempts: int = 3) -> bool:
    text = close_open_tags(text)
    if count_visible_chars(text) > TELEGRAM_HARD_LIMIT:
        text = smart_truncate(text, TELEGRAM_HARD_LIMIT)

    data = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "caption": text,
        "parse_mode": "HTML",
    }

    for attempt in range(1, max_attempts + 1):
        files = {"photo": ("cover.jpg", image_bytes, "image/jpeg")}
        try:
            logger.info(f"⏳ Отправка фото, попытка {attempt}/{max_attempts}...")
            response = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                data=data, files=files, timeout=(15, 180)
            )
            resp_json = response.json()

            if response.status_code == 200 and resp_json.get("ok"):
                logger.info(f"✅ Пост с фото! ID: {resp_json['result']['message_id']}")
                return True

            error_desc = resp_json.get("description", "")
            if "can't parse entities" in error_desc.lower():
                logger.warning("⚠️ HTML ошибка, отправляем без тегов...")
                data["caption"] = strip_html_tags(text)
                data["parse_mode"] = None
                response = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                    data=data, files=files, timeout=(15, 180)
                )
                resp_json = response.json()
                if response.status_code == 200 and resp_json.get("ok"):
                    logger.info(f"✅ Пост без HTML! ID: {resp_json['result']['message_id']}")
                    return True

            logger.error(f"❌ Ошибка Telegram: {resp_json}")
            return False

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            logger.warning(f"⚠️ Сеть ({attempt}/{max_attempts}): {e}")
            if attempt < max_attempts:
                time.sleep(5 * attempt)
                continue
            return False
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            return False

    return False


# =============================================================================
# ГЛАВНЫЙ ЦИКЛ
# =============================================================================
def main():
    logger.info("🚀 Запуск автопостинга (Спортпит без воды)...")

    post_text, topic, rubric = generate_post()
    if not post_text:
        logger.error("❌ Не удалось сгенерировать текст. Завершение.")
        sys.exit(1)

    logger.info(f"📝 ФИНАЛЬНЫЙ ТЕКСТ ({len(post_text)} / {count_visible_chars(post_text)} видимых):")
    logger.info("-" * 40)
    logger.info(post_text)
    logger.info("-" * 40)

    image_bytes = generate_image(topic, rubric)

    if image_bytes:
        success = publish_photo_to_telegram(image_bytes, post_text)
    else:
        logger.warning("⚠️ Без фото, текстом")
        success = publish_to_telegram(post_text)

    if not success:
        logger.error("❌ Не удалось опубликовать. Завершение.")
        sys.exit(1)

    logger.info("🎉 Готово!")

if __name__ == "__main__":
    main()
