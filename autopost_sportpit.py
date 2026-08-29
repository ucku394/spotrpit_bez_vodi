import os
import sys
import json
import random
import time
import logging
import urllib.parse
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

# АКТУАЛЬНЫЕ МОДЕЛИ GEMINI (август 2026)
TEXT_MODELS = [
    "gemini-3.6-flash",       # Актуальная модель (рекомендована Google)
    "gemini-flash-latest",    # Алиас — всегда указывает на последнюю flash-модель
    "gemini-2.5-flash-lite",  # Легкая версия как fallback
]

# =============================================================================
# ТЕМЫ ПО ДНЯМ НЕДЕЛИ — КАНАЛ "СПОРТПИТ БЕЗ ВОДЫ"
# Формат: независимый разбор добавки/ингредиента/уловки на основе исследований.
# Единый шаблон разбора применяется КО ВСЕМ дням (задан в get_prompt_for_today):
# Состав → Что говорит исследование → Вердикт → Цена/качество
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

    prompt = f"""Напиши пост для Telegram-канала "Спортпит без воды" — независимые разборы спортивного питания и БАДов на основе исследований, а не маркетинга бренда. Канал показывает, что реально работает, а что — развод на упаковке. Никакой скрытой рекламы за деньги без пометки.

Рубрика дня: {day_data['rubric']}
Формат: {day_data['format_hint']}
Конкретная тема поста: {topic}

ОБЯЗАТЕЛЬНАЯ СТРУКТУРА ПОСТА (единый шаблон канала, соблюдай всегда, даже в сжатом формате):
1. <b>Состав</b> — что это за вещество/продукт, из чего состоит или что заявлено на этикетке.
2. 🔬 <b>Что говорит исследование</b> — краткий honest вывод по реальным данным. Если по теме есть качественные исследования (в т.ч. систематические обзоры / метаанализы) — опиши суть вывода без выдумывания цифр и названий, которых ты не знаешь точно. Если уверенных данных нет или они противоречивы — так и напиши: "качественных независимых исследований мало / данные противоречивы". НИКОГДА не выдумывай конкретные названия исследований, авторов, журналы или цифры, если не уверен в их существовании — это подрывает доверие к каналу.
3. ⚠️ Если в теме есть маркетинговая уловка (проприетарная смесь, преувеличение, некорректная формулировка на этикетке и т.п.) — обозначь её явно с этим эмодзи.
4. <b>Вердикт</b> — обозначь одним из двух эмодзи: ✅ (работает / оправдано) или ❌ (не работает / не оправдано), либо обоими, если эффект частичный или зависит от условий. После эмодзи — 1-2 предложения итога.
5. <b>Цена/качество</b> — короткий честный вывод: стоит ли переплачивать, есть ли смысл вообще покупать, на что смотреть при выборе.

Требования к оформлению:
- Общий объём — примерно 600-900 символов, чтобы гарантированно поместиться в подпись к картинке (лимит Telegram 1024 символа).
- Используй HTML-теги для форматирования: <b>жирный</b>, <i>курсив</i>.
- Эмодзи-навигация строго по смыслу, без перегруза: 🔬 — исследование, ⚠️ — маркетинговая уловка, ✅ — работает, ❌ — не работает. Не используй другие эмодзи, кроме этих (и максимум 1 дополнительного по теме поста, если уместно).
- Если у тебя есть реальный, точно существующий источник (название организации, тип исследования, автор) — укажи его ОДНОЙ строкой в самом конце поста после текста, в формате "Источник: ...". Не выноси ссылки и цитаты в тело поста. Если уверенного источника нет — просто не добавляй эту строку, не выдумывай её.
- Не давай персональных медицинских рекомендаций и не указывай точные дозировки как предписание к действию — только контекст из исследований, с оговоркой "проконсультируйтесь со специалистом" при упоминании дозировок или взаимодействия с здоровьем.
- Не хвали и не критикуй конкретные коммерческие бренды без фактического основания.
- 1-2 хэштега в самом конце (после источника, если он есть), например #спортпит #БАДы — подбирай по теме.
- Короткий вопрос аудитории или призыв к обсуждению в конце текста (до источника/хэштегов).
- ВЫДАВАЙ ТОЛЬКО ГОТОВЫЙ ТЕКСТ ПОСТА. Никаких размышлений, комментариев модели, счетчиков слов и пояснений.
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
            if len(text) > 1024:
                logger.warning(f"⚠️ Текст от модели слишком длинный ({len(text)} симв.). Обрезаем до 1020 символов.")
                text = text[:1020].rsplit(' ', 1)[0] + "…"

            logger.info(f"✅ Текст готов: {len(text)} символов")
            return text, topic, day_data["rubric"]

    logger.error("❌ Все текстовые модели вернули пустой/короткий текст")
    return None, None, None


# =============================================================================
# СЖАТИЕ ИЗОБРАЖЕНИЯ
# =============================================================================
def compress_image(image_bytes: bytes, max_width: int = 1280, quality: int = 82) -> bytes:
    """
    Уменьшает размер файла картинки перед отправкой в Telegram:
    - ограничивает ширину (Unsplash отдаёт full-размер, иногда 3000px+)
    - конвертирует в JPEG с разумным качеством
    Это ускоряет отправку и снижает риск таймаута на медленной сети (например, GitHub Actions).
    """
    try:
        img = Image.open(BytesIO(image_bytes))
        img = img.convert("RGB")  # на случай PNG с альфа-каналом и т.п.

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

    # Используем ТОЛЬКО короткие английские ключевые слова
    # Unsplash не понимает длинные русские фразы
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

    # Выбираем 3-4 случайных ключевых слова для разнообразия фото
    selected_keywords = random.sample(base_keywords, min(4, len(base_keywords)))
    query = urllib.parse.quote(" ".join(selected_keywords))

    # URL API Unsplash
    url = f"https://api.unsplash.com/photos/random?query={query}&orientation=landscape&content_filter=high&w=1200&h=630&client_id={UNSPLASH_ACCESS_KEY}"

    headers = {
        "Accept-Version": "v1"
    }

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
                    logger.info(f"✅ Фото найдено и загружено: {len(img_response.content)} байт (Автор: {photographer})")
                    return compress_image(img_response.content)
                else:
                    logger.warning("⚠️ Пустой ответ при скачивании изображения")
                    return None

        elif response.status_code == 401:
            logger.error("❌ Неверный UNSPLASH_ACCESS_KEY! Проверьте ключ в .env или Secrets GitHub.")
            return None

        elif response.status_code == 404:
            logger.warning("⚠️ Unsplash не нашел фото по запросу. Пробуем fallback...")
            # Fallback: пробуем самый простой запрос
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
                                logger.info(f"✅ Фото найдено (fallback: {fallback_query}): {len(img_response.content)} байт (Автор: {photographer})")
                                return compress_image(img_response.content)
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка fallback запроса '{fallback_query}': {e}")
                    continue
            logger.warning("⚠️ Все fallback запросы не дали результата")
            return None

        elif response.status_code == 429:
            logger.warning("⚠️ Превышен лимит запросов к Unsplash API (50 в час)")
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
    """Публикует фото вместе с текстом в качестве единой подписи (caption).
    Делает несколько попыток с увеличенным таймаутом — на случай медленной
    сети раннера (например, GitHub Actions) или единичного сбоя соединения."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"

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
                logger.info(f"✅ Пост с картинкой и текстом опубликован единым сообщением! Message ID: {resp_json['result']['message_id']}")
                return True
            else:
                logger.error(f"❌ Ошибка отправки фото в Telegram: {resp_json}")
                return False  # ошибка от самого Telegram API (не сетевая) — повторять бессмысленно

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            logger.warning(f"⚠️ Сетевая ошибка при отправке фото (попытка {attempt}/{max_attempts}): {e}")
            if attempt < max_attempts:
                time.sleep(5 * attempt)  # пауза перед повтором, увеличивается с каждой попыткой
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
