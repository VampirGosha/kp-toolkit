"""Сборка отчётов по выгруженным CSV."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from . import parsing
from .parsing import Title


def average(items: list[Title]) -> float | None:
    values = [x.rating for x in items if x.rating is not None]
    return sum(values) / len(values) if values else None


def median(items: list[Title]) -> float | None:
    values = sorted(x.rating for x in items if x.rating is not None)
    if not values:
        return None

    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2


def distribution(items: list[Title]) -> dict[str, int]:
    counter = Counter(
        int(x.rating) for x in items if x.rating is not None
    )
    return {str(score): counter.get(score, 0) for score in range(1, 11)}


def group_stats(items: list[Title]) -> dict:
    rated = [x for x in items if x.rating is not None]
    if not rated:
        return {"n": len(items), "rated": 0, "avg": None}

    count = len(rated)
    return {
        "n": len(items),
        "rated": count,
        "avg": round(sum(x.rating for x in rated) / count, 3),
        "high_pct": round(100 * sum(x.rating >= 9 for x in rated) / count, 1),
        "low_pct": round(100 * sum(x.rating <= 5 for x in rated) / count, 1),
        "dist": distribution(items),
    }


def by_tag(titles: list[Title]) -> dict[str, list[Title]]:
    result: dict[str, list[Title]] = defaultdict(list)
    for title in titles:
        for tag in title.tags:
            result[tag].append(title)
    return dict(result)


def by_year(titles: list[Title]) -> dict[int, list[Title]]:
    result: dict[int, list[Title]] = defaultdict(list)
    for title in titles:
        if title.year:
            result[title.year].append(title)
    return dict(result)


def is_anime(title: Title) -> bool:
    return any(tag.lower() in parsing.ANIME_TAGS for tag in title.tags)


def build_summary(titles: list[Title], planned: list[Title]) -> dict:
    rated = [x for x in titles if x.rating is not None]
    unrated = [x for x in titles if x.rating is None]
    anime = [x for x in titles if is_anime(x)]

    tags = {
        tag: group_stats(items)
        for tag, items in sorted(
            by_tag(titles).items(),
            key=lambda pair: (-len(pair[1]), pair[0]),
        )
    }

    years = {
        str(year): group_stats(items)
        for year, items in sorted(by_year(titles).items())
        if len(items) >= 3
    }

    top = sorted(
        rated,
        key=lambda x: (-x.rating, x.title),
    )[:20]

    bottom = sorted(
        rated,
        key=lambda x: (x.rating, x.title),
    )[:20]

    avg = average(rated)
    anime_avg = average(anime)

    return {
        "meta": {
            "watched": len(titles),
            "rated": len(rated),
            "unrated": len(unrated),
            "planned": len(planned),
            "average": round(avg, 3) if avg is not None else None,
            "median": median(rated),
            "high_pct": round(
                100 * sum(x.rating >= 9 for x in rated) / len(rated), 1
            )
            if rated
            else None,
            "low_pct": round(
                100 * sum(x.rating <= 5 for x in rated) / len(rated), 1
            )
            if rated
            else None,
            "anime_count": len(anime),
            "anime_average": round(anime_avg, 3) if anime_avg is not None else None,
        },
        "ratings": distribution(titles),
        "tags": tags,
        "years": years,
        "anime": group_stats(anime),
        "top20": [
            [x.title, x.year, x.rating, x.tags] for x in top
        ],
        "bottom20": [
            [x.title, x.year, x.rating, x.tags] for x in bottom
        ],
        "unrated": [[x.title, x.year, x.tags] for x in unrated],
        "planned": [[x.title, x.year, x.tags] for x in planned],
        "titles": [
            [x.title, x.year, x.rating, x.tags] for x in titles
        ],
    }


def bar(count: int, max_count: int, width: int = 36) -> str:
    if max_count <= 0:
        return ""

    filled = round(width * count / max_count)
    return "█" * filled + "·" * (width - filled)


def section(lines: list[str], title: str) -> None:
    lines.append("")
    lines.append("=" * 70)
    lines.append(title)
    lines.append("=" * 70)


def render_text(summary: dict, titles: list[Title], planned: list[Title]) -> str:
    meta = summary["meta"]
    rated = [x for x in titles if x.rating is not None]
    lines: list[str] = []

    lines.append("ОТЧЁТ ПО БИБЛИОТЕКЕ КИНОПОИСКА")
    lines.append("Сгенерирован локально из CSV-файлов, ничего никуда не отправлялось.")
    lines.append("Исходные CSV не изменялись.")

    section(lines, "1. СВОДКА")

    def fmt(value: float | None, digits: int = 2) -> str:
        return "—" if value is None else f"{value:.{digits}f}"

    anime_text = f"{meta['anime_count']} шт."
    if meta["anime_average"] is not None:
        anime_text += f", средняя {meta['anime_average']:.2f}"

    lines.append(f"Просмотрено:     {meta['watched']}")
    lines.append(f"С оценкой:       {meta['rated']}")
    lines.append(f"Без оценки:      {meta['unrated']}")
    lines.append(f"В планах:        {meta['planned']}")
    lines.append(f"Средняя оценка:  {fmt(meta['average'])}")
    lines.append(f"Медиана:         {fmt(meta['median'], 1)}")
    lines.append(f"Оценки 9-10:     {fmt(meta['high_pct'], 1)}%")
    lines.append(f"Оценки 1-5:      {fmt(meta['low_pct'], 1)}%")
    lines.append(f"Аниме:           {anime_text}")

    section(lines, "2. РАСПРЕДЕЛЕНИЕ ОЦЕНОК")
    dist = summary["ratings"]
    max_count = max(dist.values()) if dist else 0

    for score in range(10, 0, -1):
        count = dist[str(score)]
        share = round(100 * count / meta["rated"], 1) if meta["rated"] else 0
        lines.append(
            f"{score:2d} | {bar(count, max_count)} {count:4d}  ({share}%)"
        )

    section(lines, "3. ВСЕ ОЦЕНКИ ПО БАЛЛАМ")
    by_rating: dict[int, list[Title]] = defaultdict(list)
    for title in rated:
        by_rating[int(title.rating)].append(title)

    for score in range(10, 0, -1):
        items = sorted(
            by_rating.get(score, []),
            key=lambda x: (x.year or 0, x.title),
        )
        if not items:
            continue

        lines.append("")
        lines.append(f"--- {score}/10 ({len(items)}) ---")
        for title in items:
            tags = ", ".join(title.tags) if title.tags else "?"
            lines.append(f"{title.label()} — {tags}")

    section(lines, "4. ЖАНРЫ И ТИПЫ")
    for tag, stats in summary["tags"].items():
        if stats["rated"] == 0:
            continue
        lines.append(
            f"{tag}: {stats['n']} шт. (оценено {stats['rated']}), "
            f"avg {stats['avg']}, "
            f"9-10: {stats['high_pct']}%, "
            f"1-5: {stats['low_pct']}%"
        )

    section(lines, "5. ГОДЫ")
    for year, stats in summary["years"].items():
        if stats["rated"] == 0:
            continue
        dist_text = " ".join(
            f"{score}={stats['dist'][str(score)]}"
            for score in range(10, 0, -1)
            if stats["dist"][str(score)]
        )
        lines.append(
            f"{year}: n={stats['n']}, avg={stats['avg']}, {dist_text}"
        )

    section(lines, "6. АНИМЕ")
    anime = summary["anime"]
    if anime["rated"]:
        lines.append(
            f"Всего: {anime['n']}, оценено: {anime['rated']}, "
            f"avg {anime['avg']}, "
            f"9-10: {anime['high_pct']}%, "
            f"1-5: {anime['low_pct']}%"
        )
        anime_titles = [x for x in titles if is_anime(x)]
        for score in range(10, 0, -1):
            items = [
                x for x in anime_titles
                if x.rating is not None and int(x.rating) == score
            ]
            items.sort(key=lambda x: x.title)
            if items:
                lines.append(
                    f"{score}: " + "; ".join(x.title for x in items)
                )
    else:
        lines.append("Аниме не найдено (проверь теги в CSV).")

    section(lines, "7. ТОП-20")
    for title, year, rating, tags in summary["top20"]:
        year_text = f" ({year})" if year else ""
        tag_text = f" — {', '.join(tags)}" if tags else ""
        lines.append(f"{rating}: {title}{year_text}{tag_text}")

    section(lines, "8. АНТИТОП-20")
    for title, year, rating, tags in summary["bottom20"]:
        year_text = f" ({year})" if year else ""
        tag_text = f" — {', '.join(tags)}" if tags else ""
        lines.append(f"{rating}: {title}{year_text}{tag_text}")

    section(lines, "9. ПРОСМОТРЕНО БЕЗ ОЦЕНКИ")
    unrated = [x for x in titles if x.rating is None]
    if unrated:
        for title in sorted(unrated, key=lambda x: x.title):
            tags = ", ".join(title.tags) if title.tags else "?"
            lines.append(f"{title.label()} — {tags}")
    else:
        lines.append("Все просмотренные произведения оценены.")

    section(lines, "10. БУДУ СМОТРЕТЬ")
    if planned:
        for title in sorted(planned, key=lambda x: (x.year or 0, x.title)):
            tags = ", ".join(title.tags) if title.tags else "?"
            lines.append(f"{title.label()} — {tags}")
    else:
        lines.append("Список планов пуст.")

    section(lines, "11. JSON-СВОДКА ДЛЯ МАШИН")
    lines.append(
        json.dumps(
            {key: value for key, value in summary.items() if key != "titles"},
            ensure_ascii=False,
            indent=2,
        )
    )

    return "\n".join(lines)


def run(data_dir: Path) -> list[Path]:
    titles, warnings = parsing.load_watched(data_dir)
    planned = parsing.load_planned(data_dir)

    if not titles:
        raise SystemExit(
            f"Не найден CSV с просмотренным в {data_dir.resolve()}.\n"
            "Сначала выполните: kp pull --user <твой_логин>"
        )

    summary = build_summary(titles, planned)

    text = render_text(summary, titles, planned)

    txt_path = data_dir / parsing.REPORT_TXT
    json_path = data_dir / parsing.REPORT_JSON

    txt_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path.write_text(text, encoding="utf-8")
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for warning in warnings:
        print(f"⚠ {warning}")

    meta = summary["meta"]
    average_text = "—" if meta["average"] is None else f"{meta['average']:.2f}"

    print(f"Просмотрено: {meta['watched']}  "
          f"(оценено {meta['rated']}, без оценки {meta['unrated']})")
    print(f"В планах:    {meta['planned']}")
    print(f"Средняя:     {average_text}")

    if meta["rated"] == 0:
        print()
        print("⚠ Оценок нет — отчёт построен только по спискам.")
        print("  Проверь, что выгрузились оценки: kp pull --user <логин>")

    print()
    print(f"✓ {txt_path}  ({txt_path.stat().st_size / 1024:.1f} KB)")
    print(f"✓ {json_path}  ({json_path.stat().st_size / 1024:.1f} KB)")

    return [txt_path, json_path]
