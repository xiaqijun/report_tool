import subprocess
from pathlib import Path

from app.config import APP_RELOAD


BASE_DIR = Path(__file__).resolve().parent.parent.parent


def run_update() -> dict[str, object]:
    steps = [
        ["git", "pull", "--ff-only"],
        ["uv", "sync"],
    ]
    outputs: list[str] = []

    for command in steps:
        completed = subprocess.run(
            command,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
        command_label = " ".join(command)
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        body = "\n".join(part for part in [stdout, stderr] if part)
        outputs.append(f"$ {command_label}\n{body or '命令执行完成。'}")
        if completed.returncode != 0:
            return {
                "ok": False,
                "summary": f"代码更新失败：{command_label}",
                "details": "\n\n".join(outputs),
            }

    return {
        "ok": True,
        "summary": "代码已更新完成。当前已启用热更新，文件变更会自动触发重载。" if APP_RELOAD else "代码已更新完成。当前未启用热更新，请手动重启服务。",
        "details": "\n\n".join(outputs),
    }