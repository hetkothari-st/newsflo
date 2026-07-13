"""One-time historical backfill: translate every existing Alert (and every
distinct category string) into every TARGET_LANGS language.

Ongoing/new-article translation is handled by the recurring scheduler job
(app/scheduler.py _run_translation), which calls the exact same
translate_pending_alerts/translate_pending_categories functions -- this
script just drives them to completion in one run instead of waiting out many
scheduler ticks.

Safe to re-run -- only targets alerts/categories still missing a translation,
and commits after each one so an interrupted run keeps whatever progress it
made.

Run with ENABLE_SCHEDULER=false (or during a maintenance window) to avoid a
race with a live scheduler tick translating the same rows concurrently --
harmless if it happens (the losing commit just fails and is retried next
batch), but wastes a Groq call.

Usage (from the backend/ directory, so `app` is importable):
    .venv/Scripts/python backfill_translations.py
"""
from app.config import settings
from app.db import SessionLocal, init_db
from app.translation.groq_translator import build_translation_client
from app.translation.job import translate_pending_alerts, translate_pending_categories

BATCH_SIZE = 25
THROTTLE_SECONDS = 3.0


def main() -> None:
    init_db()
    session = SessionLocal()
    client = build_translation_client(settings.groq_api_keys)
    total_categories = 0
    total_alerts = 0
    try:
        while True:
            n = translate_pending_categories(session, client, batch_size=BATCH_SIZE)
            total_categories += n
            if n == 0:
                break
            print(f"categories batch done: {n} translated (total {total_categories})")

        while True:
            n = translate_pending_alerts(
                session, client, limit=BATCH_SIZE, throttle_seconds=THROTTLE_SECONDS
            )
            total_alerts += n
            if n == 0:
                break
            print(f"alerts batch done: {n} translated (total {total_alerts})")
    finally:
        session.close()

    print(f"Backfill complete: {total_categories} categories, {total_alerts} alerts translated.")


if __name__ == "__main__":
    main()
