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