"""Background scheduling separated from flagship UI and voice orchestration."""
from __future__ import annotations

import logging
import threading
import time


def run_one_job(runtime, job) -> None:
    store = runtime.agent_controller.store
    tools = runtime.agent_controller.tools
    session = runtime.agent_controller.workflows.owner_session
    stop_heartbeat = threading.Event()

    def heartbeat():
        while not stop_heartbeat.wait(5):
            if runtime.stop_event.is_set():
                return
            if job.run_key:
                try:
                    if not store.heartbeat_scheduled_run(job.flow_id, job.run_key, session):
                        return
                except Exception:
                    logging.exception("Не удалось обновить heartbeat %s", job.flow_id)
                    return

    worker = None
    if job.run_key and session:
        worker = threading.Thread(
            target=heartbeat, name="GarfieldScheduleHeartbeat", daemon=True,
        )
        worker.start()

    success = False
    detail = "Прервано при остановке приложения"
    try:
        count = 0
        for step in job.steps:
            if runtime.stop_event.is_set():
                return
            tools.execute(step["tool"], step["args"])
            count += 1
        success = True
        detail = f"Выполнено шагов: {count}"
        runtime.emit("status", f"Запланированная проверка «{job.label}»: {detail}")
    except Exception as error:
        detail = f"{type(error).__name__}: {error}"[:500]
        logging.exception("Ошибка сценария %s", job.flow_id)
        runtime.emit("status", f"Ошибка сценария «{job.label}»: {error}")
    finally:
        stop_heartbeat.set()
        if worker is not None:
            worker.join(timeout=2)
        if job.run_key:
            try:
                store.finish_scheduled_run(job.flow_id, job.run_key, success, detail)
            except Exception:
                logging.exception("Не удалось записать завершение %s", job.flow_id)


def schedule_loop(runtime) -> None:
    last_update_check = 0.0
    while not runtime.stop_event.wait(15):
        if (getattr(runtime.config, "auto_check_updates", False)
                and time.monotonic() - last_update_check > 86400):
            last_update_check = time.monotonic()
            try:
                msg = runtime.agent_controller.updater.check()
                if "новых коммитов" in msg:
                    runtime.emit("status", msg)
            except Exception as error:
                logging.info("Проверка обновлений недоступна: %s", error)

        if not getattr(runtime.config, "enable_schedules", False):
            continue
        try:
            jobs = runtime.agent_controller.workflows.due_read_only()
        except Exception as error:
            logging.exception("Не удалось прочитать расписание")
            runtime.emit("status", f"Ошибка расписания: {error}")
            continue
        for job in jobs:
            if runtime.stop_event.is_set():
                return
            run_one_job(runtime, job)
