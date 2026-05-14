import subprocess
import tomllib
from pathlib import Path

from packaging.version import InvalidVersion, Version

from app.config import APP_RELOAD


BASE_DIR = Path(__file__).resolve().parent.parent.parent
REMOTE_BRANCH = "origin/main"
PYPROJECT_PATH = BASE_DIR / "pyproject.toml"


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        check=False,
    )


def _format_output(command: list[str], completed: subprocess.CompletedProcess[str]) -> str:
    command_label = " ".join(command)
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    body = "\n".join(part for part in [stdout, stderr] if part)
    return f"$ {command_label}\n{body or '命令执行完成。'}"


def _parse_project_version(pyproject_text: str) -> str:
    data = tomllib.loads(pyproject_text)
    version = str(data.get("project", {}).get("version", "")).strip()
    if not version:
        raise ValueError("pyproject.toml 未配置 project.version")
    return version


def _read_local_version() -> str:
    return _parse_project_version(PYPROJECT_PATH.read_text(encoding="utf-8"))


def _read_remote_version() -> tuple[str | None, str]:
    command = ["git", "show", f"{REMOTE_BRANCH}:pyproject.toml"]
    completed = _run_command(command)
    if completed.returncode != 0:
        return None, _format_output(command, completed)
    return _parse_project_version(completed.stdout), _format_output(command, completed)


def _is_newer_version(remote_version: str, local_version: str) -> bool:
    try:
        return Version(remote_version) > Version(local_version)
    except InvalidVersion:
        return remote_version != local_version


def check_version() -> dict[str, object]:
    outputs: list[str] = []

    fetch_command = ["git", "fetch", "origin", "main"]
    fetch_result = _run_command(fetch_command)
    outputs.append(_format_output(fetch_command, fetch_result))
    if fetch_result.returncode != 0:
        return {
            "checked": True,
            "ok": False,
            "has_update": False,
            "summary": "版本检查失败。",
            "details": "\n\n".join(outputs),
        }

    try:
        local_version = _read_local_version()
    except (OSError, ValueError, tomllib.TOMLDecodeError) as error:
        return {
            "checked": True,
            "ok": False,
            "has_update": False,
            "summary": "读取当前版本失败。",
            "details": "\n\n".join(outputs + [str(error)]),
        }
    outputs.append(f"$ read local pyproject.version\n{local_version}")

    try:
        remote_version, remote_output = _read_remote_version()
    except (ValueError, tomllib.TOMLDecodeError) as error:
        return {
            "checked": True,
            "ok": False,
            "has_update": False,
            "summary": "读取远端版本失败。",
            "details": "\n\n".join(outputs + [str(error)]),
        }
    outputs.append(remote_output)
    if remote_version is None:
        return {
            "checked": True,
            "ok": False,
            "has_update": False,
            "summary": "读取远端版本失败。",
            "details": "\n\n".join(outputs),
        }

    has_update = _is_newer_version(remote_version, local_version)

    return {
        "checked": True,
        "ok": True,
        "has_update": has_update,
        "summary": f"发现新版本，可从 v{local_version} 更新到 v{remote_version}。" if has_update else f"当前已经是最新版本 v{local_version}。",
        "details": "\n\n".join(outputs),
        "local_version": local_version,
        "remote_version": remote_version,
    }


def run_update() -> dict[str, object]:
    steps = [
        ["git", "pull", "--ff-only"],
        ["uv", "sync"],
    ]
    outputs: list[str] = []

    for command in steps:
        completed = _run_command(command)
        outputs.append(_format_output(command, completed))
        if completed.returncode != 0:
            return {
                "checked": True,
                "ok": False,
                "has_update": True,
                "summary": f"代码更新失败：{' '.join(command)}",
                "details": "\n\n".join(outputs),
            }

    try:
        current_version = _read_local_version()
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        current_version = ""

    return {
        "checked": True,
        "ok": True,
        "has_update": False,
        "summary": (f"代码已更新到 v{current_version}。当前已启用热更新，文件变更会自动触发重载。" if current_version else "代码已更新完成。当前已启用热更新，文件变更会自动触发重载。") if APP_RELOAD else (f"代码已更新到 v{current_version}。当前未启用热更新，请手动重启服务。" if current_version else "代码已更新完成。当前未启用热更新，请手动重启服务。"),
        "details": "\n\n".join(outputs),
        "local_version": current_version,
        "remote_version": current_version,
    }