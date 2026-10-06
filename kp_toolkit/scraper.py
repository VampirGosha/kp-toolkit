"""Сбор данных Кинопоиска через Playwright.

Официального публичного API у Кинопоиска нет, поэтому списки и оценки
выгружаются из твоего же аккаунта: открываются твои страницы профиля
и из HTML достаются названия, годы и оценки.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import (
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from . import parsing

BASE_URL = "https://www.kinopoisk.ru"

MAX_EMPTY_PAGES = 2
PAGE_DELAY = 1.5

WATCHED_PATHS = "movies/voted-watched"
PLANNED_PATHS = "movies/planned-to-watch"


def ensure_chromium() -> None:
    """Ставит Chromium для Playwright, если его ещё нет."""
    try:
        with sync_playwright() as p:
            executable = p.chromium.executable_path

        if Path(executable).exists():
            return

    except Exception:
        pass

    print("Chromium для Playwright не найден, устанавливаю...")

    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=False,
    )

    if result.returncode != 0:
        raise SystemExit(
            "\nНе удалось установить Chromium.\n"
            "Попробуй вручную:\n"
            "    playwright install chromium\n"
        )


def goto(page: Page, url: str) -> None:
    response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(int(PAGE_DELAY * 1000))

    if response is None:
        return

    if response.status == 429:
        print("      ⚠ HTTP 429 — слишком много запросов, жду 15 секунд...")
        time.sleep(15)
        response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

    if response is not None and response.status >= 400:
        print(f"      ⚠ HTTP {response.status}")


def wait_for_content(page: Page) -> None:
    try:
        page.locator('a[href*="/film/"], a[href*="/series/"]').first.wait_for(
            state="attached",
            timeout=10000,
        )
    except PlaywrightTimeoutError:
        page.wait_for_timeout(2000)


def extract_items(page: Page, status: str) -> list[dict]:
    """Достаёт карточки фильмов/сериалов со страницы списка.

    Селекторы эвристические: Кинопоиск периодически меняет вёрстку,
    поэтому ищем ссылки на /film/ и /series/ и поднимаемся по DOM
    до контейнера с годом или оценкой.
    """
    js = """
    (status) => {
        const result = [];
        const seen = new Set();

        const links = Array.from(document.querySelectorAll(
            'a[href*="/film/"], a[href*="/series/"]'
        ));

        for (const link of links) {
            let href = link.href || "";
            if (!href) continue;

            href = href.split("?")[0].split("#")[0];

            if (!/kinopoisk\\.ru\\/(film|series)\\//.test(href)) {
                continue;
            }

            if (seen.has(href)) continue;

            const title = (link.innerText || "").trim();
            if (!title) continue;

            let node = link;
            let container = null;

            for (let level = 0; level < 8 && node; level++, node = node.parentElement) {
                const text = (node.innerText || "").trim();

                if (text.length >= title.length &&
                    text.length <= 2500 &&
                    (
                        /\\b(19|20)\\d{2}\\b/.test(text) ||
                        /моя оценка/i.test(text) ||
                        /оценка/i.test(text)
                    )) {
                    container = node;
                    break;
                }
            }

            if (!container) {
                container = link.parentElement;
            }

            const text = (container?.innerText || "").replace(/\\s+/g, " ").trim();

            let cleanTitle = title.replace(/\\s+/g, " ").trim();

            const yearMatch = text.match(/\\b((?:19|20)\\d{2})\\b/);
            const year = yearMatch ? yearMatch[1] : "";

            let userRating = "";

            const ratingPatterns = [
                /моя\\s+оценка\\s*[:\\-]?\\s*(10|[1-9])/i,
                /ваша\\s+оценка\\s*[:\\-]?\\s*(10|[1-9])/i,
                /оценка\\s*[:\\-]?\\s*(10|[1-9])/i,
            ];

            for (const pattern of ratingPatterns) {
                const match = text.match(pattern);
                if (match) {
                    userRating = match[1];
                    break;
                }
            }

            seen.add(href);

            result.push({
                title: cleanTitle,
                year,
                user_rating: userRating,
                status,
                kinopoisk_url: href,
                raw_text: text,
            });
        }

        return result;
    }
    """

    return page.evaluate(js, status)


def extract_votes(page: Page) -> list[dict]:
    """Достаёт оценки из старого раздела /votes/."""
    js = r"""
    () => {
        const result = [];
        const seen = new Set();

        const links = Array.from(
            document.querySelectorAll('a[href*="/film/"], a[href*="/series/"]')
        );

        for (const link of links) {
            let href = link.href || "";

            if (!href) continue;

            href = href.split("?")[0].split("#")[0];

            if (!/kinopoisk\.ru\/(film|series)\//.test(href)) continue;
            if (seen.has(href)) continue;

            const title = (link.innerText || "")
                .replace(/\s+/g, " ")
                .trim();

            if (!title) continue;

            let node = link;
            let container = null;

            for (let level = 0; level < 10 && node; level++) {
                const text = (node.innerText || "")
                    .replace(/\s+/g, " ")
                    .trim();

                const hasDate = /\d{2}\.\d{2}\.\d{4}/.test(text);
                const hasRating = /(?:\s|^)(10|[1-9])(?:\s|$)/.test(text);

                if (
                    hasDate &&
                    hasRating &&
                    text.length >= title.length &&
                    text.length < 2000
                ) {
                    container = node;
                    break;
                }

                node = node.parentElement;
            }

            if (!container) {
                container = link.parentElement;
            }

            const rawText = (container?.innerText || "")
                .replace(/\s+/g, " ")
                .trim();

            const yearMatch = title.match(/\b((?:19|20)\d{2})\b/);
            const year = yearMatch ? yearMatch[1] : "";

            const dateMatch = rawText.match(
                /\b(\d{2}\.\d{2}\.\d{4}),?\s+\d{2}:\d{2}\b/
            );
            const ratedAt = dateMatch ? dateMatch[1] : "";

            let userRating = "";

            if (dateMatch) {
                const afterDate = rawText.substring(
                    dateMatch.index + dateMatch[0].length
                );

                const ratingMatch =
                    afterDate.match(/^\s+(10|[1-9])(?:\s|$)/);

                if (ratingMatch) {
                    userRating = ratingMatch[1];
                }
            }

            if (!userRating) {
                const allMatches = [
                    ...rawText.matchAll(/(?:^|\s)(10|[1-9])(?:\s|$)/g)
                ];

                if (allMatches.length) {
                    userRating = allMatches[allMatches.length - 1][1];
                }
            }

            seen.add(href);

            result.push({
                title,
                year,
                user_rating: userRating,
                rated_at: ratedAt,
                kinopoisk_url: href,
                raw_text: rawText,
            });
        }

        return result;
    }
    """

    return page.evaluate(js)


def save_csv(path: Path, items: list[dict], fields: list[str]) -> None:
    if not items:
        print(f"⚠ Ничего не найдено для {path.name}")
        return

    parsing.write_csv(path, items, fields)
    print(f"✓ {path}  ({len(items)} записей)")


def scrape_list(page: Page, url: str, status: str) -> list[dict]:
    all_items: list[dict] = []
    seen_urls: set[str] = set()
    empty_pages = 0

    print()
    print("=" * 70)
    print(f"Экспорт: {status}")
    print("=" * 70)

    for page_number in range(1, 2001):
        page_url = f"{url}?page={page_number}"
        print(f"[{page_number:03d}] {page_url}")

        try:
            goto(page, page_url)
            wait_for_content(page)
            items = extract_items(page, status)

        except Exception as exc:
            print(f"      ⚠ {exc}, повтор через 5 секунд...")
            time.sleep(5)

            try:
                goto(page, page_url)
                wait_for_content(page)
                items = extract_items(page, status)
            except Exception as retry_exc:
                print(f"      ✗ Повтор не удался: {retry_exc}")
                break

        new_items = []

        for item in items:
            item_url = item["kinopoisk_url"]
            if item_url not in seen_urls:
                seen_urls.add(item_url)
                all_items.append(item)
                new_items.append(item)

        print(
            f"      найдено: {len(items)}, "
            f"новых: {len(new_items)}, "
            f"всего: {len(all_items)}"
        )

        if not new_items:
            empty_pages += 1
        else:
            empty_pages = 0

        if empty_pages >= MAX_EMPTY_PAGES:
            print("      Список закончился.")
            break

    return all_items


def scrape_votes(page: Page, url: str) -> list[dict]:
    all_items: list[dict] = []
    seen_urls: set[str] = set()
    empty_pages = 0

    print()
    print("=" * 70)
    print("Экспорт оценок")
    print("=" * 70)

    for page_number in range(1, 2001):
        page_url = f"{url}?page={page_number}"
        print(f"[{page_number:03d}] {page_url}")

        try:
            goto(page, page_url)
            items = extract_votes(page)

        except Exception as exc:
            print(f"      ⚠ {exc}, повтор через 5 секунд...")
            time.sleep(5)

            try:
                goto(page, page_url)
                items = extract_votes(page)
            except Exception as retry_exc:
                print(f"      ✗ Повтор не удался: {retry_exc}")
                break

        new_items = []

        for item in items:
            item_url = item["kinopoisk_url"]
            if item_url not in seen_urls:
                seen_urls.add(item_url)
                all_items.append(item)
                new_items.append(item)

        rated_count = sum(bool(x["user_rating"]) for x in new_items)
        print(
            f"      найдено: {len(items)}, "
            f"новых: {len(new_items)}, "
            f"с оценкой: {rated_count}, "
            f"всего: {len(all_items)}"
        )

        if not new_items:
            empty_pages += 1
        else:
            empty_pages = 0

        if empty_pages >= MAX_EMPTY_PAGES:
            print("      Список закончился.")
            break

    return all_items


def merge_votes(data_dir: Path) -> bool:
    """Склеивает оценки из /votes/ со списка просмотренного."""
    watched_path = data_dir / parsing.MERGED

    if not watched_path.exists():
        watched_path = data_dir / parsing.WATCHED

    ratings_path = data_dir / parsing.RATINGS

    if not watched_path.exists() or not ratings_path.exists():
        print("⚠ Объединение пропущено: нет CSV с просмотренным или оценками.")
        return False

    watched = parsing.read_csv(watched_path)
    ratings = parsing.read_csv(ratings_path)

    if not watched or not ratings:
        print("⚠ Объединение пропущено: один из файлов пуст.")
        return False

    ratings_by_url: dict[str, dict] = {}
    for item in ratings:
        url = parsing.normalize_url(item.get("kinopoisk_url", ""))
        if url:
            ratings_by_url[url] = item

    merged: list[dict] = []
    matched = 0

    fields = list(watched[0].keys())
    for extra in ("user_rating", "rated_at"):
        if extra not in fields:
            fields.append(extra)

    for row in watched:
        item = dict(row)
        rating = ratings_by_url.get(
            parsing.normalize_url(row.get("kinopoisk_url", ""))
        )

        if rating and rating.get("user_rating"):
            item["user_rating"] = rating["user_rating"]
            item["rated_at"] = rating.get("rated_at", "")
            matched += 1
        else:
            item.setdefault("user_rating", "")
            item.setdefault("rated_at", "")

        merged.append(item)

    out_path = data_dir / parsing.MERGED
    parsing.write_csv(out_path, merged, fields)

    print()
    print(f"Просмотрено:      {len(watched)}")
    print(f"Оценок подтянуто: {matched}")
    print(f"Без оценки:       {len(merged) - matched}")
    print(f"✓ {out_path}")

    return True


def login_if_needed(page: Page, check_url: str | None = None) -> None:
    print()
    print("Открываю Кинопоиск...")

    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)

    print()
    print("Если Кинопоиск показал страницу входа — войди в аккаунт в браузере.")
    print("Скрипт не читает пароль и ничего никуда не отправляет.")
    print()

    try:
        input("Когда увидишь свой профиль, нажми Enter... ")
    except EOFError:
        pass

    if check_url:
        page.goto(check_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)


def list_url(user: str, path: str) -> str:
    return f"{BASE_URL}/user/{user}/{path}/"


def pull(
    user: str,
    data_dir: Path,
    votes_user: str | None = None,
    skip_votes: bool = False,
) -> None:
    """Полная выгрузка: просмотренное, планы, оценки."""
    data_dir.mkdir(parents=True, exist_ok=True)
    ensure_chromium()

    profile_dir = data_dir / parsing.BROWSER_PROFILE
    votes_user = votes_user or user

    with sync_playwright() as p:
        print("Открываю браузер с постоянным профилем:")
        print(f"  {profile_dir.resolve()}")

        context: BrowserContext = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            viewport={"width": 1440, "height": 1000},
            locale="ru-RU",
            timezone_id="Asia/Omsk",
        )

        page = context.pages[0] if context.pages else context.new_page()

        try:
            login_if_needed(page, list_url(user, WATCHED_PATHS))

            watched = scrape_list(
                page,
                list_url(user, WATCHED_PATHS),
                "watched",
            )
            save_csv(
                data_dir / parsing.WATCHED,
                watched,
                ["title", "year", "user_rating", "status",
                 "kinopoisk_url", "raw_text"],
            )

            planned = scrape_list(
                page,
                list_url(user, PLANNED_PATHS),
                "planned",
            )
            save_csv(
                data_dir / parsing.PLANNED,
                planned,
                ["title", "year", "user_rating", "status",
                 "kinopoisk_url", "raw_text"],
            )

            rated = [x for x in watched if x.get("user_rating")]

            print()
            print("=" * 70)
            print(f"Просмотрено: {len(watched)}, из них с оценкой: {len(rated)}")
            print(f"В планах:    {len(planned)}")
            print("=" * 70)

            if skip_votes:
                print()
                print("Шаг с оценками пропущен (--skip-votes).")
                _ensure_merged_from_watched(data_dir, watched, rated)
            else:
                votes = scrape_votes(page, list_url(votes_user, "votes"))

                if votes:
                    save_csv(
                        data_dir / parsing.RATINGS,
                        votes,
                        ["title", "year", "user_rating", "rated_at",
                         "kinopoisk_url", "raw_text"],
                    )
                    merge_votes(data_dir)
                else:
                    print()
                    print("⚠ Оценки выгрузить не удалось.")
                    print("  Возможно, раздел /votes/ изменился или закрыт.")
                    print("  Список просмотренного сохранён, отчёт построится без оценок.")
                    _ensure_merged_from_watched(data_dir, watched, rated)

            print()
            print("Готово. Данные лежат в:")
            print(f"  {data_dir.resolve()}")

        finally:
            print()
            try:
                input("Закрой браузер и нажми Enter... ")
            except EOFError:
                pass
            context.close()


def _ensure_merged_from_watched(
    data_dir: Path,
    watched: list[dict],
    rated: list[dict],
) -> None:
    """Если оценок из /votes/ нет, но они были в списке — кладём их в MERGED
    только когда MERGED ещё не существует (чтобы не затереть старые данные)."""
    merged_path = data_dir / parsing.MERGED

    if not rated:
        return

    if merged_path.exists():
        return

    parsing.write_csv(
        merged_path,
        watched,
        ["title", "year", "user_rating", "status",
         "kinopoisk_url", "raw_text"],
    )
    print(f"✓ {merged_path.name}  ({len(watched)} записей)")
