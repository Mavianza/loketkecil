"""Validasi input sebelum operasi database."""

from datetime import date
import json
import re


class AppError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def require(condition, message, status=400):
    if not condition:
        raise AppError(message, status)


def text(value, limit, label, *, blank=False):
    require(isinstance(value, str), f"{label} harus berupa teks.")
    result = value.strip()
    require((blank or bool(result)) and len(result) <= limit, f"{label} maksimal {limit} karakter" + ("." if blank else " dan tidak boleh kosong."))
    require(not any(ord(c) < 32 or 127 <= ord(c) < 160 or 0xD800 <= ord(c) <= 0xDFFF for c in result), f"{label} mengandung karakter tidak valid.")
    return result


def positive(value, label):
    require(type(value) is int and 1 <= value <= 2147483647, f"{label} harus bilangan bulat positif.")
    return value


def day(value):
    require(isinstance(value, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)), "Tanggal harus YYYY-MM-DD.")
    try:
        valid = date.fromisoformat(value)
    except ValueError as exc:
        raise AppError("Tanggal kalender tidak valid.") from exc
    require(2000 <= valid.year <= 2100, "Tanggal harus berada pada tahun 2000–2100.")
    return valid.isoformat()


def parse_json(raw):
    def pairs(items):
        obj = {}
        for key, value in items:
            require(key not in obj, "Nama kolom JSON tidak boleh berulang.")
            obj[key] = value
        return obj
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(AppError("Angka JSON tidak valid.")))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise AppError("Isi permintaan bukan JSON UTF-8 yang valid.") from exc


def command(value):
    require(type(value) is dict, "Permintaan harus objek JSON.")
    action = value.get("action")
    fields = {
        "create": {"action", "title", "day", "counters"},
        "issue": {"action", "session_id", "alias"},
        "call": {"action", "session_id", "counter_id", "expected_version"},
        "finish": {"action", "session_id", "ticket_id", "expected_version"},
        "skip": {"action", "session_id", "ticket_id", "expected_version"},
        "requeue": {"action", "session_id", "ticket_id", "expected_version"},
        "cancel": {"action", "session_id", "ticket_id", "expected_version"},
        "close": {"action", "session_id"}, "demo": {"action"},
    }
    require(isinstance(action, str) and action in fields, "Tindakan tidak dikenal.")
    require(set(value) == fields[action], "Kolom permintaan tidak sesuai tindakan.")
    result = {"action": action}
    for key in ("session_id", "counter_id", "ticket_id", "expected_version"):
        if key in value:
            result[key] = positive(value[key], key)
    if action == "create":
        result["title"] = text(value["title"], 80, "Nama layanan")
        result["day"] = day(value["day"])
        counters = value["counters"]
        require(type(counters) is list and 1 <= len(counters) <= 4, "Gunakan 1–4 loket.")
        result["counters"] = [text(c, 30, "Nama loket") for c in counters]
        require(len({c.casefold() for c in result["counters"]}) == len(counters), "Nama loket tidak boleh sama.")
    if action == "issue":
        result["alias"] = text(value["alias"], 40, "Alias", blank=True)
    return result


def request_key(value):
    require(isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{8,80}", value)), "Idempotency-Key harus 8–80 huruf/angka/underscore/tanda hubung.")
    return value
