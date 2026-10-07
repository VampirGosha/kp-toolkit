"""Загрузка CSV и разбор полей, которые отдаёт Кинопоиск."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

WATCHED = "kinopoisk_watched.csv"
PLANNED = "kinopoisk_planned.csv"
RATINGS = "kinopoisk_ratings.csv"
MERGED = "kinopoisk_watched_with_ratings.csv"
REPORT_TXT = "report.txt"
REPORT_JSON = "report.json"
BROWSER_PROFILE = ".kp-browser"

COLUMN_ALIASES = {
    "title": ("title", "name", "название"),
    "year": ("year", "год"),
    "rating": ("user_rating", "rating", "оценка"),
    "type": ("type", "тип", "media_type"),
    "genres": ("genres", "genre", "жанры", "жанр"),
    "url": ("kinopoisk_url", "url", "link", "ссылка"),
    "rated_at": ("rated_at", "дата оценки"),
}

# Карточка Кинопоиска отдаёт название вида:
#     "Форма голоса 2016, аниме"
# Разбираем на чистое название, год и тег (жанр/тип).
TITLE_RE = re.compile(
    r"^(?P<title>.+)\s+(?P<year>(?:19|20)\d{2})(?:\s*,\s*(?P<tag>[^,]+))?$"
)

TAG_SPLIT_RE = re.compile(r"[,;/|]+")

ANIME_TAGS = {"аниме", "anime"}


@dataclass
class Title:
    title: str
    year: int | None = None
    rating: float | None = None
    tags: list[str] = field(default_factory=list)
    url: str = ""
    rated_at: str = ""

    def label(self) -> str:
        if self.year:
            return f"{self.title} ({self.year})"
        return self.title


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def find_column(rows: list[dict], key: str) -> str | None:
    if not rows:
        return None

    aliases = COLUMN_ALIASES[key]
    columns = list(rows[0].keys())

    for alias in aliases:
        if alias in columns:
            return alias

    lower = {c.lower(): c for c in columns}
    for alias in aliases:
        if alias.lower() in lower:
            return lower[alias.lower()]

    for column in columns:
        for alias in aliases:
            if alias.lower() in column.lower():
                return column

    return None


def get(row: dict, column: str | None) -> str:
    if not column:
        return ""
    return str(row.get(column, "") or "").strip()


def split_title(raw: str) -> tuple[str, int | None, str | None]:
    """'Форма голоса 2016, аниме' -> ('Форма голоса', 2016, 'аниме')."""
    raw = re.sub(r"\s+", " ", raw or "").strip()
    if not raw:
        return "", None, None

    match = TITLE_RE.match(raw)
    if not match:
        return raw, None, None

    title = match.group("title").strip()
    year = int(match.group("year"))
    tag = match.group("tag")
    tag = tag.strip() if tag else None

    if not title:
        return raw, None, None

    return title, year, tag


def parse_year(value: str) -> int | None:
    match = re.search(r"(?:19|20)\d{2}", value or "")
    return int(match.group()) if match else None


def parse_rating(value: str) -> float | None:
    if not value:
        return None

    match = re.search(r"\d+(?:[.,]\d+)?", value)
    if not match:
        return None

    try:
        number = float(match.group().replace(",", "."))
    except ValueError:
        return None

    return number if 0 <= number <= 10 else None


def split_tags(value: str) -> list[str]:
    return [tag.strip() for tag in TAG_SPLIT_RE.split(value or "") if tag.strip()]


def load_titles(path: Path) -> tuple[list[Title], list[str]]:
    """Читает CSV и возвращает тайтлы плюс список предупреждений."""
    rows = read_csv(path)
    warnings: list[str] = []

    if not rows:
        return [], warnings

    columns = {key: find_column(rows, key) for key in COLUMN_ALIASES}

    if not columns["title"]:
        warnings.append(f"{path.name}: не найдена колонка с названием")
        return [], warnings

    if not columns["rating"]:
        warnings.append(f"{path.name}: не найдена колонка с оценкой")

    titles: list[Title] = []
    empty_titles = 0

    for row in rows:
        raw_title = get(row, columns["title"])
        clean_title, title_year, tag = split_title(raw_title)

        if not clean_title:
            empty_titles += 1
            continue

        year = parse_year(get(row, columns["year"])) or title_year

        tags: list[str] = []
        for key in ("type", "genres"):
            for item in split_tags(get(row, columns[key])):
                if item not in tags:
                    tags.append(item)

        if tag and tag not in tags:
            tags.append(tag)

        titles.append(
            Title(
                title=clean_title,
                year=year,
                rating=parse_rating(get(row, columns["rating"])),
                tags=tags,
                url=get(row, columns["url"]),
                rated_at=get(row, columns["rated_at"]),
            )
        )

    if empty_titles:
        warnings.append(f"{path.name}: пропущено {empty_titles} строк(и) с пустым названием")

    return titles, warnings


def load_watched(data_dir: Path) -> tuple[list[Title], list[str]]:
    merged = data_dir / MERGED
    watched = data_dir / WATCHED
    path = merged if merged.exists() else watched
    return load_titles(path)


def load_planned(data_dir: Path) -> tuple[list[Title], list[str]]:
    return load_titles(data_dir / PLANNED)


def normalize_url(url: str) -> str:
    if not url:
        return ""

    url = url.split("?")[0].split("#")[0]
    return url.rstrip("/") + "/"
