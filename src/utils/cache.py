from cachetools import TTLCache

# кэш на 10 минут
events_cache = TTLCache(maxsize=1024, ttl=600)

# кэш на 3 минуты
system_cache = TTLCache(maxsize=512, ttl=180)


def clear_event_cache(event_id=None):
    """
    Очищает кеш для конкретного события или весь кеш событий.

    Args:
        event_id: ID события, кеш которого нужно очистить. Если None, очищает весь кеш.
    """
    if event_id is None:
        events_cache.clear()
        return

    keys_to_remove = []
    for key in list(events_cache.keys()):
        # Проверяем, является ли ключ кортежем и содержит ли он наш event_id
        if isinstance(key, tuple) and any(str(event_id) in str(k) for k in key):
            keys_to_remove.append(key)

    for key in keys_to_remove:
        if key in events_cache:
            del events_cache[key]
