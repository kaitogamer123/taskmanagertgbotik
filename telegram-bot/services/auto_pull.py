"""
Система автоматического обновления из GitHub (автопулл), аналогичная VigarikSQD:
  1) В фоне раз в AUTO_PULL_INTERVAL секунд проверяет новые коммиты на GitHub (`git fetch`).
  2) Если в репозитории появились обновления — автоматически скачивает их (`git pull`),
     обновляет зависимости из `requirements.txt` (не затрагивая `.env` и базы в `PlanesUser/`)
     и перезапускает процесс бота на лету (`os.execv`).
  3) Также поддерживает ручной запуск через скрипт `./update.sh` (screen) или команду `/update`.

Что оптимизировано по расходу ресурсов:
  * `git fetch` выполняется раз в AUTO_PULL_INTERVAL (по умолчанию 15 минут), а не каждую минуту;
  * за одну проверку запускается минимум git-процессов: fetch + один rev-parse;
  * если удалённая ветка не изменилась — никаких `git pull`/`git reset` не выполняется
    (раньше при отсутствии upstream `git reset --hard` мог выполняться каждую минуту);
  * все git-команды ограничены по времени и не могут зависнуть навсегда.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from aiogram import Bot

from config import AUTO_PULL_ENABLED, AUTO_PULL_INTERVAL, BASE_DIR

logger = logging.getLogger(__name__)

# Максимальное время на одну git-команду (секунды)
GIT_TIMEOUT = 60.0
GIT_SHORT_TIMEOUT = 15.0

_git_config_done = False


@dataclass
class PullResult:
    updated: bool
    old_commit: str
    new_commit: str
    message: str


async def _run_cmd(
    args: list[str], cwd: Path, timeout: float = GIT_TIMEOUT
) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        with contextlib.suppress(Exception):
            proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()
        return 124, "", f"превышено время ожидания ({timeout:.0f} сек.)"

    stdout = stdout_b.decode("utf-8", errors="replace").strip()
    stderr = stderr_b.decode("utf-8", errors="replace").strip()
    return proc.returncode or 0, stdout, stderr


async def find_git_root() -> Path | None:
    try:
        code, out, _ = await _run_cmd(
            ["git", "rev-parse", "--show-toplevel"],
            BASE_DIR,
            timeout=GIT_SHORT_TIMEOUT,
        )
        if code == 0 and out:
            return Path(out)
    except FileNotFoundError:
        logger.warning("Утилита git не установлена — автопулл отключён.")
    return None


async def _ensure_git_config(git_root: Path) -> None:
    """core.fileMode=false выставляем один раз за запуск, а не на каждой проверке."""
    global _git_config_done
    if _git_config_done:
        return
    await _run_cmd(
        ["git", "config", "core.fileMode", "false"],
        git_root,
        timeout=GIT_SHORT_TIMEOUT,
    )
    _git_config_done = True


async def _resolve_remote_ref(git_root: Path) -> str | None:
    """Возвращает ref удалённой ветки (upstream, иначе origin/main или origin/master)."""
    code, out, _ = await _run_cmd(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        git_root,
        timeout=GIT_SHORT_TIMEOUT,
    )
    if code == 0 and out and out != "HEAD":
        return out

    for ref in ("origin/main", "origin/master"):
        code, out, _ = await _run_cmd(
            ["git", "rev-parse", "--verify", "--quiet", ref],
            git_root,
            timeout=GIT_SHORT_TIMEOUT,
        )
        if code == 0 and out:
            return ref
    return None


async def check_and_pull_updates(force_pull: bool = False) -> PullResult:
    git_root = await find_git_root()
    if git_root is None:
        return PullResult(
            updated=False,
            old_commit="",
            new_commit="",
            message="Папка бота не привязана к Git-репозиторию (используй git clone).",
        )

    await _ensure_git_config(git_root)

    _, old_out, _ = await _run_cmd(
        ["git", "rev-parse", "HEAD"], git_root, timeout=GIT_SHORT_TIMEOUT
    )
    old_sha = (old_out or "").strip()[:7]

    fetch_code, _, fetch_err = await _run_cmd(
        ["git", "fetch", "--quiet", "--prune"], git_root
    )
    if fetch_code != 0:
        return PullResult(
            updated=False,
            old_commit=old_sha,
            new_commit=old_sha,
            message=f"Не удалось связаться с GitHub: {fetch_err or 'ошибка сети'}",
        )

    remote_ref = await _resolve_remote_ref(git_root)
    if remote_ref is None:
        return PullResult(
            updated=False,
            old_commit=old_sha,
            new_commit=old_sha,
            message=(
                "Не удалось определить удалённую ветку (upstream). "
                "Проверь: git branch --set-upstream-to=origin/main"
            ),
        )

    # Один вызов вместо двух отдельных rev-parse
    rev_code, rev_out, _ = await _run_cmd(
        ["git", "rev-parse", "HEAD", remote_ref],
        git_root,
        timeout=GIT_SHORT_TIMEOUT,
    )
    parts = rev_out.split()
    if rev_code != 0 or len(parts) != 2:
        return PullResult(
            updated=False,
            old_commit=old_sha,
            new_commit=old_sha,
            message=f"Не удалось прочитать коммиты ветки {remote_ref}.",
        )

    old_full, remote_full = parts
    old_sha = old_full[:7]
    new_sha = remote_full[:7]

    # Главное: если коммит не изменился — НЕ делаем ни pull, ни reset.
    if remote_full == old_full:
        return PullResult(
            updated=False,
            old_commit=old_sha,
            new_commit=old_sha,
            message=f"Уже установлена актуальная версия ({old_sha}).",
        )

    pull_code, pull_out, pull_err = await _run_cmd(
        ["git", "pull", "--ff-only", "--quiet"], git_root
    )
    if pull_code != 0:
        # Защищённый сброс только отслеживаемых Git-файлов (.env и PlanesUser/ в .gitignore!)
        reset_code, _, reset_err = await _run_cmd(
            ["git", "reset", "--hard", remote_ref], git_root
        )
        if reset_code != 0:
            return PullResult(
                updated=False,
                old_commit=old_sha,
                new_commit=old_sha,
                message=f"Ошибка git pull: {pull_err or reset_err}",
            )
        pull_out = "Синхронизировано с удалённой веткой GitHub."

    _, new_out, _ = await _run_cmd(
        ["git", "rev-parse", "HEAD"], git_root, timeout=GIT_SHORT_TIMEOUT
    )
    new_full = (new_out or remote_full).strip()
    new_sha = new_full[:7]

    changed = new_full != old_full
    if changed:
        req_file = BASE_DIR / "requirements.txt"
        if req_file.exists():
            pip_code, _, pip_err = await _run_cmd(
                [sys.executable, "-m", "pip", "install", "-q", "-r", str(req_file)],
                BASE_DIR,
            )
            if pip_code != 0:
                return PullResult(
                    updated=False,
                    old_commit=old_sha,
                    new_commit=new_sha,
                    message=(
                        "Код обновлён, но pip install завершился с ошибкой: "
                        f"{pip_err or 'неизвестная ошибка'}. "
                        "Перезапуск отменён — исправь зависимости и сделай /restart."
                    ),
                )

    return PullResult(
        updated=changed,
        old_commit=old_sha,
        new_commit=new_sha,
        message=pull_out or f"Обновлено {old_sha} -> {new_sha}",
    )


async def restart_bot_process(bot: Bot) -> None:
    """Аккуратно закрывает сессию бота и перезапускает текущий Python-процесс."""
    logger.info("Перезапуск процесса бота для применения обновлений...")
    try:
        await bot.session.close()
    except Exception:  # noqa: BLE001
        pass
    await asyncio.sleep(0.5)
    os.execv(sys.executable, [sys.executable, str(BASE_DIR / "bot.py")])


async def run_auto_pull(bot: Bot) -> None:
    """Фоновый цикл автопулла с GitHub."""
    if not AUTO_PULL_ENABLED:
        logger.info("Фоновый автопулл отключён (AUTO_PULL_ENABLED=0).")
        return

    git_root = await find_git_root()
    if git_root is None:
        logger.info(
            "Git-репозиторий не обнаружен в %s — фоновый автопулл не активен.",
            BASE_DIR,
        )
        return

    logger.info(
        "Система автопулла запущена (интервал %s сек., репозиторий: %s)",
        AUTO_PULL_INTERVAL,
        git_root,
    )
    while True:
        await asyncio.sleep(AUTO_PULL_INTERVAL)
        try:
            res = await check_and_pull_updates()
            if res.updated:
                logger.info(
                    "🚀 Автопулл: получено обновление %s -> %s! Перезапускаю бота...",
                    res.old_commit,
                    res.new_commit,
                )
                await restart_bot_process(bot)
        except Exception:  # noqa: BLE001
            logger.exception("Ошибка в цикле автопулла")
