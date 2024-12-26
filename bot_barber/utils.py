# utils.py
from telegram.ext import ContextTypes

from translations import MESSAGES

def tr(context: ContextTypes.DEFAULT_TYPE, key: str) -> str:
    """Повертає переклад рядка по ключу і поточній мові користувача."""
    lang = context.user_data.get('lang', 'ua')  # за замовчуванням українська
    return MESSAGES.get(lang, MESSAGES['ua']).get(key, key)
