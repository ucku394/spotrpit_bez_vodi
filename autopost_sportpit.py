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

TELEGRAM_VISIBLE_LIMIT = 850
TELEGRAM_HARD_LIMIT = 1024
MIN_POST_LENGTH = 400  # Минимум 400 символов
REQUIRED_SECTIONS = ['Состав', 'исследование', 'Вердикт', 'Цена/качество']  # Обязательные разделы

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
def strip_html_tags(html_text: str) -> str:
    return re.sub(r'<[^>]+>', '', html_text)

def count_visible_chars(html_text: str) -> int:
    return len(strip_html_tags(html_text))

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

def ensure_caption_length(html_text: str) -> str:
    visible_len = count_visible_chars(html_text)
    total_len = len(html_text)

    if visible_len <= TELEGRAM_VISIBLE_LIMIT and total_len <= TELEGRAM_HARD_LIMIT:
        return close_open_tags(html_text)

    logger.warning(f"⚠️ Текст превышает лимит (Видимых: {visible_len}, Всего: {total_len}). Обрезаем...")

    lines = html_text.split('\n')
    result_lines = []
    current_visible = 0
    current_total = 0

    safe_visible_limit = TELEGRAM_VISIBLE_LIMIT - 30
    safe_total_limit = TELEGRAM_HARD_LIMIT - 30

    for line in lines:
        v_len = len(strip_html_tags(line))
        t_len = len(line)

        if (current_visible + v_len <= safe_visible_limit) and (current_total + t_len + 1 <= safe_total_limit):
            result_lines.append(line)
            current_visible += v_len
            current_total += t_len + 1
        else:
            break

    truncated = '\n'.join(result_lines).rstrip()
    
    if count_visible_chars(truncated) < visible_len:
        truncated = truncated.rstrip() + "…"

    return close_open_tags(truncated)


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
    weekday = datetime.now().weekday()
    day_data = THEMES[weekday]
    topic = pick_topic(weekday)

    prompt = f"""Ты — эксперт по спортивному питанию. Напиши РАЗВЁРНУТЫЙ пост для Telegram-канала "Спортпит без воды".

РУБРИКА: {day_data['rubric']}
ТЕМА: {topic}

СТРУКТУРА ПОСТА (ОБЯЗАТЕЛЬНО выполни ВСЕ 6 пунктов, каждый подробно):

1️⃣ <b>Состав</b> — что это за вещество/продукт, из чего состоит, основные компоненты (МИНИМУМ 2-3 предложения)

2️⃣ 🔬 <b>Что говорят исследования</b> — реальные научные данные об эффективности, конкретные результаты исследований (МИНИМУМ 3-4 предложения)

3️ ⚠️ <b>Маркетинговая уловка</b> — что обещают производители vs реальность, разоблачение мифов (МИНИМУМ 2-3 предложения). Если продукт честный — напиши "✅ Честный продукт без скрытых уловок"

4️⃣ <b>Вердикт</b> — ✅ работает / ❌ не работает / ⚠️ спорно (выбери одно и ОБЪЯСНИ почему в 1-2 предложениях)

5️⃣ <b>Цена/качество</b> — стоит ли покупать, соотношение цены и эффекта (МИНИМУМ 1-2 предложения)

6️⃣ <b>Вопрос аудитории</b> — короткий вопрос подписчикам для вовлечения (5-10 слов)

7️⃣ Хэштеги — 2 релевантных хэштега

КРИТИЧЕСКИ ВАЖНО:
- Пиши ПОДРОБНО, с фактами и конкретикой
- Общий объём: 600-900 видимых символов (не считая HTML-тегов)
- Каждый пункт должен быть развёрнутым, не менее 2-3 предложений
- Используй теги <b>жирный</b> для заголовков пунктов
- Каждый пункт с новой строки
- НЕ выдумывай названия исследований, авторов, журналов
- Выдай ТОЛЬКО готовый пост, без вступлений

ВАЖНО: Пост должен быть ПОЛНОСТЬЮ завершён, включая все 6 пунктов структуры!
"""
    return prompt, topic, day_data


# =============================================================================
# GEMINI API
# =============================================================================
def validate_post_structure(text: str) -> tuple:
    """Проверяет, содержит ли пост все обязательные разделы."""
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
            "maxOutputTokens": 2048,  # Увеличено для развёрнутых ответов
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
        
        # Убираем вступительные фразы и markdown
        text = re.sub(r'^(Вот ваш пост:|Конечно, вот пост:|Разбор темы:|Пост для канала:)\s*\n?', '', text, flags=re.IGNORECASE)
        text = re.sub(r'^```\s*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)

        visible_len = count_visible_chars(text)
        
        # Проверка минимальной длины
        if visible_len < MIN_POST_LENGTH:
            logger.warning(f"⚠️ {model_name}: текст слишком короткий ({visible_len} символов, минимум {MIN_POST_LENGTH})")
            return None
        
        # Проверка структуры
        is_valid, missing = validate_post_structure(text)
        if not is_valid:
            logger.warning(f"⚠️ {model_name}: не хватает разделов: {', '.join(missing)}")
            return None

        if len(text) > 50:
            logger.info(f"✅ {model_name}: сгенерировано {visible_len} видимых символов, все разделы на месте")
            return text
        
        return None

    except Exception as e:
        logger.warning(f"⚠️ Ошибка {model_name}: {e}")
        return None

def generate_post():
    """Генерирует пост с проверкой качества и полноты."""
    prompt_text, topic, day_data = get_prompt_for_today()

    for attempt in range(10):  # До 10 попыток
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
    
    if len(text) > 1024:
        text = text[:1020] + "…"
        text = close_open_tags(text)

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
    if len(text) > 1024:
        logger.warning("⚠️ АВАРИЙНАЯ ОБРЕЗКА: текст > 1024 символов!")
        text = text[:1020] + "…"
        text = close_open_tags(text)

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
