"""Shared by the GUI tests: a Streamlit server, and hands for a browser.

The server is started with ``subprocess.Popen`` so the test owns exactly one
process id, and stops exactly that one. Nothing here looks processes up by name.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Where browser screenshots go: the usage report and docs/GUI.md show them.
SCREENSHOTS = Path(os.environ.get("GUI_SCREENSHOT_DIR", REPO_ROOT / "docs" / "screenshots"))

#: A screenshot committed to the repository stays small.
SCREENSHOT_LIMIT = 300 * 1024


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@contextmanager
def streamlit_server(app: Path, *, env: dict[str, str], log: Path):
    """Run ``streamlit run app`` headless; yield (url, pid); stop that pid."""
    port = free_port()
    command = [sys.executable, "-m", "streamlit", "run", str(app),
               "--server.address", "127.0.0.1", "--server.port", str(port),
               "--server.headless", "true", "--browser.gatherUsageStats", "false",
               "--server.fileWatcherType", "none"]
    url = f"http://127.0.0.1:{port}"
    with log.open("w") as stream:
        process = subprocess.Popen(command, cwd=str(REPO_ROOT), env=env,
                                   stdout=stream, stderr=subprocess.STDOUT)
        try:
            for _ in range(240):
                if process.poll() is not None:
                    raise RuntimeError(f"streamlit exited ({process.returncode}); see {log}")
                try:
                    with urllib.request.urlopen(url + "/_stcore/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except (urllib.error.URLError, ConnectionError, OSError):
                    time.sleep(0.5)
            else:
                raise RuntimeError("streamlit did not become healthy")
            yield url, process.pid
        finally:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def settle(page, timeout: int = 60000) -> None:
    """Wait until Streamlit has finished the rerun a click or an edit started."""
    page.wait_for_timeout(400)
    # "hidden" also holds for an absent widget, so this returns at once when
    # Streamlit is idle; a timeout means the rerun never finished, and the
    # test must fail rather than read a page that is still changing.
    page.locator('[data-testid="stStatusWidget"]').wait_for(state="hidden", timeout=timeout)
    page.wait_for_timeout(300)


# Streamlit's data editor draws on a canvas; its accessible table mirrors the
# cells, which is how what was typed is read back and checked.
ROW_HEIGHT, HEADER_HEIGHT = 35, 36


def grid_cells(grid) -> list[str]:
    return grid.locator("td").all_inner_texts()


def _cell_xy(grid, row: int, column: int, columns: int):
    box = grid.bounding_box()
    width = box["width"] / columns
    return (box["x"] + width * (column + 0.5),
            box["y"] + HEADER_HEIGHT + ROW_HEIGHT * row + ROW_HEIGHT / 2)


def _type_once(page, grid, row: int, column: int, text: str, columns: int) -> None:
    x, y = _cell_xy(grid, row, column, columns)
    page.mouse.click(x, y)
    page.wait_for_timeout(300)
    page.keyboard.press("Enter")
    page.wait_for_timeout(400)
    page.keyboard.press("Control+A")
    page.keyboard.type(text, delay=20)
    page.keyboard.press("Enter")
    settle(page)
    page.keyboard.press("Escape")
    settle(page)


def fill_grid(page, grid, rows: list[tuple[str, ...]], *, columns: int = 3) -> None:
    """Make the editor hold exactly ``rows``, typing only the cells that differ.

    A click that lands while Streamlit redraws the grid can edit the cell the
    selection sits on instead of the one clicked. So nothing is trusted: after
    every pass the whole table is read back from the grid's accessible mirror,
    and the pass repeats until every cell -- not just the last one typed -- is
    what the caller asked for.
    """
    expected = [cell for row in rows for cell in row]
    for _ in range(6):
        if grid_cells(grid) == expected:
            return
        for index, wanted in enumerate(expected):
            row, column = divmod(index, columns)
            shown = grid_cells(grid)
            if len(shown) > index and shown[index] == wanted:
                continue
            append_row(page, grid, row, columns=columns)
            _type_once(page, grid, row, column, wanted, columns)
    raise AssertionError(f"the grid holds {grid_cells(grid)}, not {expected}")


def append_row(page, grid, row: int, *, columns: int = 3) -> None:
    """Click the editor's trailing row until row ``row`` exists."""
    for _ in range(4):
        if len(grid_cells(grid)) >= columns * (row + 1):
            return
        x, y = _cell_xy(grid, row, 0, columns)
        page.mouse.click(x, y)
        settle(page)
        page.keyboard.press("Escape")
        settle(page)
    raise AssertionError(f"could not add row {row}: {grid_cells(grid)}")


def save_screenshot(locator, name: str) -> Path:
    """Screenshot an element into docs/screenshots, kept under the size limit."""
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOTS / name
    locator.screenshot(path=str(path))
    if path.stat().st_size > SCREENSHOT_LIMIT:
        from PIL import Image

        image = Image.open(path).convert("RGB")
        image.quantize(colors=128, method=Image.Quantize.MEDIANCUT).save(path, optimize=True)
    assert path.stat().st_size <= SCREENSHOT_LIMIT, (path, path.stat().st_size)
    return path
