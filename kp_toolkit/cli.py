"""Командная строка kp-toolkit."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import report, scraper


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kp",
        description=(
            "Выгрузка и анализ твоей библиотеки Кинопоиска: "
            "списки, оценки и отчёт по вкусу."
        ),
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    pull = subparsers.add_parser(
        "pull",
        help="выгрузить просмотренное, планы и оценки через браузер",
    )
    pull.add_argument(
        "--user",
        required=True,
        help="логин профиля в адресе (kinopoisk.ru/user/ЛОГИН/)",
    )
    pull.add_argument(
        "--votes-user",
        default=None,
        help="если адрес страницы оценок отличается (обычно числовой ID)",
    )
    pull.add_argument(
        "--dir",
        default="data",
        help="папка для данных (по умолчанию: data)",
    )
    pull.add_argument(
        "--skip-votes",
        action="store_true",
        help="не выгружать оценки, только списки",
    )

    report_parser = subparsers.add_parser(
        "report",
        help="построить отчёт из уже выгруженных CSV",
    )
    report_parser.add_argument(
        "--dir",
        default="data",
        help="папка с данными (по умолчанию: data)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = Path(args.dir)

    if args.command == "pull":
        scraper.pull(
            user=args.user,
            data_dir=data_dir,
            votes_user=args.votes_user,
            skip_votes=args.skip_votes,
        )
        print()
        print("Теперь собери отчёт:")
        print(f"  kp report --dir {args.dir}")
        return 0

    report.run(data_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
