"""Shared ripgrep subprocess wrapper."""
import shutil
import subprocess


class RgNotInstalled(RuntimeError):
    """raised when `rg` binary is not on PATH"""


_INSTALL_HINT = (
    "未找到 ripgrep。请安装："
    "apt install ripgrep / brew install ripgrep / scoop install ripgrep"
)


def run_rg(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Call ripgrep with the given args (list form, no shell).

    Returns: (returncode, stdout, stderr)
    Raises:
        RgNotInstalled: when `rg` is not on PATH
        TimeoutError: when subprocess exceeds `timeout` seconds
    """
    rg_path = shutil.which("rg")
    if rg_path is None:
        raise RgNotInstalled(_INSTALL_HINT)

    try:
        result = subprocess.run(
            [rg_path, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as e:
        raise TimeoutError(f"ripgrep 超时（{timeout}s）") from e
