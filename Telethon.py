import asyncio
import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path

from telethon import TelegramClient, events, utils
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import (
    CreateForumTopicRequest,
    ForwardMessagesRequest,
    GetDialogFiltersRequest,
    GetForumTopicsRequest,
)


BASE_DIR = Path(__file__).resolve().parent
TOPIC_PAGE_SIZE = 100
MAX_TOPIC_NAME_LENGTH = 120
MAX_DAY_CACHE_SIZE = 7
DIRECT_WRITE_PATHS = set()




def configure_stdio():
    log_file = BASE_DIR / "bot.log"
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            try:
                file_stream = open(log_file, "a", encoding="utf-8")
                setattr(sys, stream_name, file_stream)
            except Exception:
                pass
        elif hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def load_json_file(path, default):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default.copy() if isinstance(default, dict) else default
    except json.JSONDecodeError as exc:
        print(f"⚠️ File JSON lỗi định dạng: {path.name}: {exc}")
        return default.copy() if isinstance(default, dict) else default


def write_json_atomic(path, data):
    ensure_directory(path.parent)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    path_key = str(path)
    if path_key in DIRECT_WRITE_PATHS or temp_path.exists():
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
        return

    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
    try:
        temp_path.replace(path)
    except PermissionError:
        DIRECT_WRITE_PATHS.add(path_key)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
        try:
            temp_path.unlink()
        except OSError:
            pass


def ensure_directory(path):
    path.mkdir(parents=True, exist_ok=True)


def extract_day_string(value, fallback_day):
    if isinstance(value, str):
        candidate = value[:10]
        try:
            datetime.strptime(candidate, "%Y-%m-%d")
            return candidate
        except ValueError:
            pass
    return fallback_day


def get_message_day_key(message=None, entry=None):
    if message is not None:
        message_date = getattr(message, "date", None)
        if message_date is not None:
            try:
                if getattr(message_date, "tzinfo", None):
                    return message_date.astimezone().strftime("%Y-%m-%d")
                return message_date.strftime("%Y-%m-%d")
            except Exception:
                pass

    fallback_day = datetime.now().strftime("%Y-%m-%d")
    if entry is not None:
        return extract_day_string(entry.get("updated_at"), fallback_day)

    return fallback_day


def get_message_map_day_path(day_key):
    return message_map_dir / f"{day_key}.json"


def build_message_key(chat_id, message_id):
    return f"{chat_id}:{message_id}"


def get_chat_display_name(chat):
    return getattr(chat, "title", None) or getattr(chat, "username", None) or f"User_{chat.id}"


def normalize_chat_id(chat_id):
    if chat_id is None:
        return None

    try:
        normalized_id, _ = utils.resolve_id(chat_id)
        return normalized_id
    except Exception:
        return chat_id


def is_same_chat(chat_id, entity):
    if entity is None:
        return False

    entity_id = getattr(entity, "id", None)
    if chat_id == entity_id or normalize_chat_id(chat_id) == entity_id:
        return True

    try:
        return chat_id == utils.get_peer_id(entity)
    except Exception:
        return False


def build_topic_name(source_name, topic_title=None):
    if topic_title:
        name = f"{source_name}_{topic_title}"
    else:
        name = source_name

    name = " ".join(name.split())
    if len(name) <= MAX_TOPIC_NAME_LENGTH:
        return name

    return f"{name[:MAX_TOPIC_NAME_LENGTH - 3].rstrip()}..."


def summarize_entities(entities):
    result = []
    for entity in entities or []:
        item = {
            "type": type(entity).__name__,
            "offset": getattr(entity, "offset", None),
            "length": getattr(entity, "length", None),
        }
        for attr in ("url", "language", "document_id", "custom_emoji_id", "user_id"):
            value = getattr(entity, attr, None)
            if value is not None:
                item[attr] = str(value)
        result.append(item)
    return result


def summarize_media(message):
    media = getattr(message, "media", None)
    if media is None:
        return None

    result = {"type": type(media).__name__}

    photo = getattr(media, "photo", None)
    if hasattr(photo, "id"):
        result["photo_id"] = photo.id

    document = getattr(media, "document", None)
    if hasattr(document, "id"):
        result["document_id"] = document.id

    webpage = getattr(media, "webpage", None)
    if webpage is not None:
        result["webpage_type"] = type(webpage).__name__
        result["url"] = getattr(webpage, "url", None)
        result["site_name"] = getattr(webpage, "site_name", None)

    poll = getattr(media, "poll", None)
    if hasattr(poll, "id"):
        result["poll_id"] = poll.id

    if hasattr(media, "value"):
        result["value"] = getattr(media, "value", None)

    return result


def build_message_signature(message):
    payload = {
        "text": message.raw_text or "",
        "entities": summarize_entities(message.entities),
        "media": summarize_media(message),
        "reply_markup": type(message.reply_markup).__name__ if message.reply_markup else None,
        "grouped_id": getattr(message, "grouped_id", None),
        "post_author": getattr(message, "post_author", None),
        "via_bot_id": getattr(message, "via_bot_id", None),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def extract_message_id_from_result(result):
    if result is None:
        return None

    if isinstance(result, list):
        first_item = result[0] if result else None
        return getattr(first_item, "id", None)

    direct_id = getattr(result, "id", None)
    if isinstance(direct_id, int):
        return direct_id

    for update in getattr(result, "updates", []) or []:
        message = getattr(update, "message", None)
        if hasattr(message, "id"):
            return message.id

        update_id = getattr(update, "id", None)
        if isinstance(update_id, int):
            return update_id

    return None


def rebuild_message_map_index():
    index = {}
    if not message_map_dir.exists():
        return index

    for day_file in sorted(message_map_dir.glob("*.json")):
        if day_file.name == message_map_index_file.name:
            continue

        day_key = day_file.stem
        day_map = load_json_file(day_file, {})
        for map_key in day_map:
            index[map_key] = day_key

    return index


def migrate_legacy_message_map():
    if not legacy_message_map_file.exists():
        return {}

    legacy_map = load_json_file(legacy_message_map_file, {})
    if not legacy_map:
        return {}

    ensure_directory(message_map_dir)
    fallback_day = datetime.fromtimestamp(legacy_message_map_file.stat().st_mtime).strftime(
        "%Y-%m-%d"
    )
    day_buckets = {}

    for map_key, entry in legacy_map.items():
        day_key = get_message_day_key(entry=entry)
        if day_key == datetime.now().strftime("%Y-%m-%d") and "updated_at" not in entry:
            day_key = fallback_day
        day_buckets.setdefault(day_key, {})[map_key] = entry

    for day_key, day_map in day_buckets.items():
        write_json_atomic(get_message_map_day_path(day_key), day_map)

    index = {}
    for day_key, day_map in day_buckets.items():
        for map_key in day_map:
            index[map_key] = day_key

    write_json_atomic(message_map_index_file, index)
    return index


configure_stdio()


def load_config():
    """Load cấu hình từ config.json."""
    config_path = BASE_DIR / "config.json"
    if not config_path.exists():
        print("❌ File config.json không tìm thấy!")
        print("📋 Tạo file config.json từ config.example.json và điền thông tin.")
        sys.exit(1)

    data = load_json_file(config_path, {})
    if not data.get("api_id") or not data.get("api_hash"):
        print("❌ config.json thiếu api_id hoặc api_hash!")
        sys.exit(1)

    return data


config = load_config()

api_id = config["api_id"]
api_hash = config["api_hash"]
session_name = config.get("session_name", "my_session")
recv_group = config.get("recv_group", "recv_autoforwarding")
max_message_map_entries = config.get("max_message_map_entries", 150000)
topic_cache_file = BASE_DIR / "topic_cache.json"
message_map_dir = BASE_DIR / "message_map"
message_map_index_file = message_map_dir / "_index.json"
legacy_message_map_file = BASE_DIR / "message_map.json"

BLACKLIST = config.get("blacklist", [])
BLACKLIST_FOLDERS = config.get("blacklist_folders", [])
folder_blacklist_chat_ids = set()
FOLDER_REFRESH_INTERVAL = config.get("folder_refresh_interval", 3600)

client = TelegramClient(str(BASE_DIR / session_name), api_id, api_hash)

topic_cache = load_json_file(topic_cache_file, {})
ensure_directory(message_map_dir)
message_map_index = load_json_file(message_map_index_file, {})
if not message_map_index:
    message_map_index = rebuild_message_map_index()
    if not message_map_index:
        message_map_index = migrate_legacy_message_map()
message_map_day_cache = {}

topic_locks = {}
topic_locks_lock = asyncio.Lock()
recv_entity_lock = asyncio.Lock()
topic_cache_save_lock = asyncio.Lock()
message_map_save_lock = asyncio.Lock()

recv_entity_cache = None
source_topic_title_cache = {}
_folder_refresh_task = None


async def save_cache():
    snapshot = dict(topic_cache)
    async with topic_cache_save_lock:
        await asyncio.to_thread(write_json_atomic, topic_cache_file, snapshot)


def load_message_map_day(day_key):
    day_map = message_map_day_cache.get(day_key)
    if day_map is None:
        if len(message_map_day_cache) >= MAX_DAY_CACHE_SIZE:
            oldest_key = min(message_map_day_cache.keys())
            message_map_day_cache.pop(oldest_key, None)
        day_map = load_json_file(get_message_map_day_path(day_key), {})
        message_map_day_cache[day_key] = day_map
    return day_map


def get_message_map_entry(map_key):
    day_key = message_map_index.get(map_key)
    if not day_key:
        return None

    day_map = load_message_map_day(day_key)
    entry = day_map.get(map_key)
    if entry is None:
        message_map_index.pop(map_key, None)
    return entry


def set_message_map_entry(map_key, entry, day_key):
    changed_days = set()
    previous_day = message_map_index.get(map_key)

    if previous_day and previous_day != day_key:
        previous_day_map = load_message_map_day(previous_day)
        if map_key in previous_day_map:
            previous_day_map.pop(map_key, None)
            changed_days.add(previous_day)

    day_map = load_message_map_day(day_key)
    day_map[map_key] = entry
    message_map_index[map_key] = day_key
    changed_days.add(day_key)
    return changed_days


def delete_message_map_entry(map_key):
    day_key = message_map_index.pop(map_key, None)
    if not day_key:
        return None, None

    day_map = load_message_map_day(day_key)
    entry = day_map.pop(map_key, None)
    return day_key, entry


def find_message_map_entry_by_suffix(suffix):
    for map_key in message_map_index:
        if map_key.endswith(suffix):
            return map_key, get_message_map_entry(map_key)
    return None, None


def write_message_map_storage(index_snapshot, day_snapshots):
    ensure_directory(message_map_dir)
    for day_key, snapshot in day_snapshots.items():
        write_json_atomic(get_message_map_day_path(day_key), snapshot)
    write_json_atomic(message_map_index_file, index_snapshot)


async def save_message_map(day_keys=None):
    target_days = {day_key for day_key in (day_keys or set()) if day_key}
    index_snapshot = dict(message_map_index)
    day_snapshots = {
        day_key: dict(load_message_map_day(day_key))
        for day_key in target_days
    }

    async with message_map_save_lock:
        await asyncio.to_thread(write_message_map_storage, index_snapshot, day_snapshots)


async def cleanup_old_message_map_entries():
    """Xóa các day file cũ nhất khi tổng entries vượt ngưỡng."""
    day_counts = {}
    for day_key in message_map_index.values():
        day_counts[day_key] = day_counts.get(day_key, 0) + 1

    sorted_days = sorted(day_counts.keys())

    while len(message_map_index) > max_message_map_entries and sorted_days:
        oldest_day = sorted_days.pop(0)
        day_map = load_message_map_day(oldest_day)
        for map_key in list(day_map.keys()):
            message_map_index.pop(map_key, None)
        day_map.clear()
        message_map_day_cache.pop(oldest_day, None)
        day_file = get_message_map_day_path(oldest_day)
        try:
            day_file.unlink()
        except OSError:
            pass
        print(f"🧹 Đã xóa message map ngày {oldest_day} (cleanup)")

    index_snapshot = dict(message_map_index)
    async with message_map_save_lock:
        await asyncio.to_thread(write_json_atomic, message_map_index_file, index_snapshot)


async def get_recv_group_entity(refresh=False):
    global recv_entity_cache

    async with recv_entity_lock:
        if recv_entity_cache is not None and not refresh:
            return recv_entity_cache

        entity = None
        if isinstance(recv_group, str) and recv_group.lstrip("-").isdigit():
            entity = await client.get_entity(int(recv_group))
        else:
            recv_group_username = recv_group.lstrip("@").lower()
            async for dialog in client.iter_dialogs():
                dialog_username = getattr(dialog.entity, "username", None)
                if dialog.name == recv_group:
                    entity = dialog.entity
                    break
                if dialog_username and dialog_username.lower() == recv_group_username:
                    entity = dialog.entity
                    break

        if entity is None:
            raise ValueError(f"Group '{recv_group}' không tìm thấy")

        recv_entity_cache = entity
        return recv_entity_cache


def is_blacklisted(chat):
    """Kiểm tra xem chat có trong blacklist không (bao gồm cả folder blacklist)."""
    for item in BLACKLIST:
        if isinstance(item, int) and chat.id == item:
            return True
        if isinstance(item, str):
            if item.lstrip("-").isdigit() and chat.id == int(item):
                return True
            if hasattr(chat, "title") and chat.title == item:
                return True
            if hasattr(chat, "username") and chat.username:
                if item in (chat.username, f"@{chat.username}"):
                    return True

    # Kiểm tra blacklist theo folder
    if chat.id in folder_blacklist_chat_ids:
        return True

    return False


async def refresh_folder_blacklist():
    """Load danh sách chat IDs từ các folder bị blacklist."""
    global folder_blacklist_chat_ids
    if not BLACKLIST_FOLDERS:
        return

    try:
        result = await client(GetDialogFiltersRequest())
        filters = getattr(result, 'filters', result) if not isinstance(result, list) else result
        new_ids = set()

        for dialog_filter in filters:
            title = getattr(dialog_filter, 'title', None)
            # title có thể là string hoặc TextWithEntities
            if hasattr(title, 'text'):
                title = title.text
            if title and title in BLACKLIST_FOLDERS:
                # Lấy included_peers (các chat trong folder)
                include_peers = getattr(dialog_filter, 'include_peers', []) or []
                for peer in include_peers:
                    peer_id = getattr(peer, 'user_id', None) \
                        or getattr(peer, 'channel_id', None) \
                        or getattr(peer, 'chat_id', None)
                    if peer_id:
                        new_ids.add(peer_id)
                print(f"📂 Folder '{title}': {len(include_peers)} chat(s) đã thêm vào blacklist")

        folder_blacklist_chat_ids = new_ids
        print(f"📂 Tổng cộng {len(folder_blacklist_chat_ids)} chat bị blacklist theo folder")
    except Exception as exc:
        print(f"⚠️ Lỗi khi load folder blacklist: {exc}")


async def folder_blacklist_refresh_loop():
    """Tự động refresh folder blacklist theo chu kỳ."""
    while True:
        await asyncio.sleep(FOLDER_REFRESH_INTERVAL)
        print("🔄 Đang refresh folder blacklist...")
        await refresh_folder_blacklist()


async def find_forum_topic(peer, *, topic_name=None, topic_id=None):
    offset_topic = 0
    seen_offsets = set()

    while True:
        result = await client(
            GetForumTopicsRequest(
                peer=peer,
                offset_date=0,
                offset_id=0,
                offset_topic=offset_topic,
                limit=TOPIC_PAGE_SIZE,
            )
        )
        topics = getattr(result, "topics", None) or []

        for topic in topics:
            if topic_name is not None and getattr(topic, "title", None) == topic_name:
                return topic
            if topic_id is not None and getattr(topic, "id", None) == topic_id:
                return topic

        if len(topics) < TOPIC_PAGE_SIZE:
            return None

        next_offset = getattr(topics[-1], "id", 0)
        if not next_offset or next_offset in seen_offsets:
            return None

        seen_offsets.add(next_offset)
        offset_topic = next_offset


async def get_source_topic_title(chat, topic_id):
    cache_key = build_message_key(chat.id, topic_id)
    if cache_key in source_topic_title_cache:
        return source_topic_title_cache[cache_key]

    topic = await find_forum_topic(chat, topic_id=topic_id)
    if topic and getattr(topic, "title", None):
        source_topic_title_cache[cache_key] = topic.title
        return topic.title

    return None


async def get_or_create_topic(group_entity, topic_name):
    """Lấy hoặc tạo topic với tên được chỉ định (thread-safe)."""
    async with topic_locks_lock:
        if topic_name not in topic_locks:
            topic_locks[topic_name] = asyncio.Lock()
        lock = topic_locks[topic_name]

    async with lock:
        if topic_name in topic_cache:
            print(f"💾 Lấy từ cache: '{topic_name}' (ID: {topic_cache[topic_name]})")
            return topic_cache[topic_name]

        try:
            topic = await find_forum_topic(group_entity, topic_name=topic_name)
            if topic is not None:
                topic_cache[topic_name] = topic.id
                await save_cache()
                print(f"✅ Tìm thấy topic '{topic_name}' (ID: {topic.id})")
                return topic.id
        except Exception as exc:
            print(f"⚠️ Lỗi khi lấy danh sách topic: {exc}")

        try:
            print(f"🔨 Đang tạo topic mới: '{topic_name}'...")
            new_topic = await client(
                CreateForumTopicRequest(
                    peer=group_entity,
                    title=topic_name,
                    random_id=random.randint(1, 2**63 - 1),
                )
            )

            topic_id = extract_message_id_from_result(new_topic)
            if topic_id is None:
                raise ValueError("Không lấy được topic_id từ response tạo topic")

            topic_cache[topic_name] = topic_id
            await save_cache()
            print(f"🆕 Đã tạo topic mới '{topic_name}' (ID: {topic_id})")
            return topic_id

        except Exception as exc:
            print(f"❌ Lỗi khi tạo topic '{topic_name}': {exc}")
            try:
                topic = await find_forum_topic(group_entity, topic_name=topic_name)
                if topic is not None:
                    topic_cache[topic_name] = topic.id
                    await save_cache()
                    print(f"✅ Tìm lại được topic '{topic_name}' sau khi create lỗi")
                    return topic.id
            except Exception as retry_exc:
                print(f"⚠️ Retry lookup topic thất bại: {retry_exc}")
            return None


async def remember_forward(chat, message, forwarded_id, topic_id, source_name):
    if not forwarded_id:
        return

    map_key = build_message_key(chat.id, message.id)
    day_key = get_message_day_key(message=message)
    entry = {
        "forwarded_id": forwarded_id,
        "topic_id": topic_id,
        "source_name": source_name,
        "message_signature": build_message_signature(message),
        "source_chat_id": chat.id,
        "source_message_id": message.id,
        "storage_day": day_key,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    changed_days = set_message_map_entry(map_key, entry, day_key)
    await save_message_map(changed_days)

    if len(message_map_index) > max_message_map_entries:
        await cleanup_old_message_map_entries()


@client.on(events.NewMessage)
async def handler(event):
    try:
        recv_entity = await get_recv_group_entity()
    except Exception as exc:
        print(f"❌ Không resolve được group đích: {exc}")
        return

    if is_same_chat(event.chat_id, recv_entity):
        return

    chat = await event.get_chat()

    if is_blacklisted(chat):
        source_name = get_chat_display_name(chat)
        print(f"🚫 Bỏ qua tin nhắn từ blacklist: {source_name}")
        return

    text = event.raw_text or "<non-text message>"
    source_name = get_chat_display_name(chat)

    topic_title = None
    reply_to = getattr(event.message, "reply_to", None)
    if reply_to and getattr(reply_to, "forum_topic", False):
        topic_id_source = getattr(reply_to, "reply_to_top_id", None) or getattr(
            reply_to, "reply_to_msg_id", None
        )
        if topic_id_source:
            try:
                topic_title = await get_source_topic_title(chat, topic_id_source)
            except Exception as exc:
                print(f"⚠️ Error getting topic name: {exc}")

    final_name = build_topic_name(source_name, topic_title)

    print("=" * 60)
    print(f"📨 From: {final_name}")
    print(f"💬 Message: {text[:100]}{'...' if len(text) > 100 else ''}")
    print("=" * 60)

    topic_id = await get_or_create_topic(recv_entity, final_name)

    try:
        if topic_id:
            result = await client(
                ForwardMessagesRequest(
                    from_peer=chat,
                    id=[event.message.id],
                    to_peer=recv_entity,
                    top_msg_id=topic_id,
                )
            )
            forwarded_msg_id = extract_message_id_from_result(result)
            await remember_forward(chat, event.message, forwarded_msg_id, topic_id, final_name)

            if forwarded_msg_id:
                print(
                    f"✅ Đã forward vào topic '{final_name}' (ID: {topic_id}) | Msg ID: {forwarded_msg_id}"
                )
            else:
                print(
                    "⚠️ Không lấy được forwarded message ID, edit tracking sẽ không hoạt động cho tin nhắn này"
                )
                print(f"✅ Đã forward vào topic '{final_name}' (ID: {topic_id})")
            return

        result = await event.message.forward_to(recv_entity)
        forwarded_msg_id = extract_message_id_from_result(result)
        await remember_forward(chat, event.message, forwarded_msg_id, None, final_name)
        print("⚠️ Forward vào General (không tạo được topic)")

    except FloodWaitError as e:
        print(f"⏳ FloodWait: chờ {e.seconds}s...")
        await asyncio.sleep(e.seconds + 1)
        try:
            if topic_id:
                result = await client(
                    ForwardMessagesRequest(
                        from_peer=chat,
                        id=[event.message.id],
                        to_peer=recv_entity,
                        top_msg_id=topic_id,
                    )
                )
            else:
                result = await event.message.forward_to(recv_entity)
            forwarded_msg_id = extract_message_id_from_result(result)
            await remember_forward(chat, event.message, forwarded_msg_id, topic_id, final_name)
            print(f"✅ Đã forward sau FloodWait vào '{final_name}'")
        except Exception as retry_exc:
            print(f"❌ Retry sau FloodWait thất bại: {retry_exc}")
    except Exception as exc:
        print(f"❌ Lỗi khi forward vào topic: {exc}")
        try:
            result = await event.message.forward_to(recv_entity)
            forwarded_msg_id = extract_message_id_from_result(result)
            await remember_forward(chat, event.message, forwarded_msg_id, None, final_name)
            print("⚠️ Đã forward vào General thay thế")
        except Exception as fallback_exc:
            print(f"❌ Fallback forward vào General cũng lỗi: {fallback_exc}")


@client.on(events.MessageEdited)
async def edit_handler(event):
    """Xử lý khi tin nhắn bị edit."""
    try:
        recv_entity = await get_recv_group_entity()
    except Exception as exc:
        print(f"❌ Không resolve được group đích khi xử lý edit: {exc}")
        return

    if is_same_chat(event.chat_id, recv_entity):
        return

    chat = await event.get_chat()
    if is_blacklisted(chat):
        return

    map_key = build_message_key(chat.id, event.message.id)
    msg_info = get_message_map_entry(map_key)
    if not msg_info:
        return

    new_signature = build_message_signature(event.message)
    old_signature = msg_info.get("message_signature")
    if old_signature == new_signature:
        print(f"ℹ️ Bỏ qua edit metadata-only: {msg_info['source_name']} | {map_key}")
        return

    new_text = event.message.raw_text or "<non-text message>"

    print("=" * 60)
    print("✏️ EDIT DETECTED!")
    print(f"📍 Source: {msg_info['source_name']}")
    print(f"💬 New content: {new_text[:100]}{'...' if len(new_text) > 100 else ''}")
    print("=" * 60)

    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = "⚠️ **TIN NHẮN ĐÃ BỊ CHỈNH SỬA**\n"
        log_message += f"🕐 Thời gian: {timestamp}\n"
        log_message += f"📍 Nguồn: {msg_info['source_name']}\n"
        log_message += "🔗 Forward lại tin nhắn khi edit\n"

        await client.send_message(
            recv_entity,
            log_message,
            reply_to=msg_info["forwarded_id"],
        )

        if msg_info.get("topic_id"):
            await client(
                ForwardMessagesRequest(
                    from_peer=chat,
                    id=[event.message.id],
                    to_peer=recv_entity,
                    top_msg_id=msg_info["topic_id"],
                )
            )
        else:
            await event.message.forward_to(recv_entity)

        day_key = message_map_index.get(map_key) or msg_info.get("storage_day") or get_message_day_key(entry=msg_info)
        msg_info["message_signature"] = new_signature
        msg_info["storage_day"] = day_key
        msg_info["updated_at"] = timestamp
        changed_days = set_message_map_entry(map_key, msg_info, day_key)
        await save_message_map(changed_days)

        print(f"✅ Đã forward tin nhắn edit và gửi log vào '{msg_info['source_name']}'")

    except Exception as exc:
        print(f"❌ Lỗi khi xử lý edit: {exc}")


@client.on(events.MessageDeleted)
async def delete_handler(event):
    """Xử lý khi tin nhắn bị xóa."""
    print("\n" + "🗑️" * 20)
    print("🔍 MESSAGE DELETED EVENT:")
    print(f"   - deleted_ids: {event.deleted_ids}")
    print(f"   - chat_id: {event.chat_id}")
    print("🗑️" * 20 + "\n")

    deleted_ids = event.deleted_ids
    chat_id = event.chat_id
    if not chat_id:
        return

    try:
        recv_entity = await get_recv_group_entity()
    except Exception as exc:
        print(f"❌ Lỗi khi lấy recv group: {exc}")
        return

    if is_same_chat(chat_id, recv_entity):
        print("ℹ️ Bỏ qua MessageDeleted trong recv_autoforwarding")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message_map_changed = False
    changed_days = set()

    for deleted_id in deleted_ids:
        exact_key = build_message_key(normalize_chat_id(chat_id), deleted_id)
        used_key = exact_key
        msg_info = get_message_map_entry(exact_key)

        if not msg_info:
            suffix = f":{deleted_id}"
            stored_key, stored_value = find_message_map_entry_by_suffix(suffix)
            if stored_key:
                msg_info = stored_value
                used_key = stored_key
                print(f"🔁 Fallback match: delete {exact_key} -> stored {stored_key}")

        if msg_info:
            log_message = (
                "🗑️ **TIN NHẮN ĐÃ BỊ XÓA**\n"
                f"🕐 Thời gian: {timestamp}\n"
                f"📍 Nguồn: {msg_info.get('source_name', 'Unknown')}\n"
                f"🔗 Original: `{deleted_id}` (key: `{used_key}`)\n"
                "🔁 Log này đang reply vào bản forward của tin nhắn đã bị xóa.\n"
            )

            try:
                await client.send_message(
                    recv_entity,
                    log_message,
                    reply_to=msg_info["forwarded_id"],
                )
                print(f"✅ Đã gửi log (reply) cho tin nhắn bị xóa: {used_key}")
                deleted_day, _ = delete_message_map_entry(used_key)
                if deleted_day:
                    changed_days.add(deleted_day)
                    message_map_changed = True
            except Exception as exc:
                print(f"❌ Lỗi khi gửi log (reply) cho tin nhắn bị xóa {used_key}: {exc}")

        else:
            log_message = (
                "🗑️ **TIN NHẮN ĐÃ BỊ XÓA (CHƯA ĐƯỢC FORWARD)**\n"
                f"🕐 Thời gian: {timestamp}\n"
                f"📍 Chat ID: `{chat_id}`\n"
                f"🔗 Message ID: `{deleted_id}`\n"
            )

            try:
                await client.send_message(recv_entity, log_message)
                print(f"⚠️ Deleted message {exact_key} not in message_map → đã gửi log riêng lẻ")
            except Exception as exc:
                print(f"❌ Lỗi khi gửi log cho tin nhắn chưa được forward {exact_key}: {exc}")

    if message_map_changed:
        await save_message_map(changed_days)


async def main_loop():
    global _folder_refresh_task
    while True:
        try:
            if _folder_refresh_task and not _folder_refresh_task.done():
                _folder_refresh_task.cancel()

            await client.start()
            recv_entity = await get_recv_group_entity(refresh=True)

            # Load folder blacklist khi khởi động
            await refresh_folder_blacklist()
            # Chạy refresh loop trong background
            _folder_refresh_task = asyncio.create_task(folder_blacklist_refresh_loop())

            print(f"🚀 Auto-forward đang chạy... forward vào group '{recv_group}'")
            print(f"📌 Nhóm đích: {get_chat_display_name(recv_entity)} ({recv_entity.id})")
            print("📋 Mỗi kênh/group sẽ được forward vào topic riêng với tên tương ứng")
            print("🔒 Race condition protection: ENABLED")
            print("✏️ Edit tracking: CONTENT-ONLY")
            print(f"🗂️ Message map: {message_map_dir.name}/YYYY-MM-DD.json ({len(message_map_index)} keys)")
            if BLACKLIST:
                print(f"🚫 Blacklist: {len(BLACKLIST)} mục được bỏ qua")
            if BLACKLIST_FOLDERS:
                print(f"📂 Blacklist folders: {BLACKLIST_FOLDERS}")
            print("-" * 60)
            await client.run_until_disconnected()
        except Exception as exc:
            print(f"❌ Bot gặp lỗi: {exc}, sẽ thử reconnect sau 5s...")
            await asyncio.sleep(5)


def check_single_instance():
    """Kiểm tra chỉ chạy 1 instance duy nhất (Windows mutex)."""
    if sys.platform == "win32":
        import ctypes
        mutex = ctypes.windll.kernel32.CreateMutexW(None, True, "TelemessageAutoforward_Mutex")
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            print("⚠️ Bot đã đang chạy. Thoát.")
            sys.exit(0)
        globals()["_instance_mutex"] = mutex


if __name__ == "__main__":
    check_single_instance()
    asyncio.run(main_loop())
