from __future__ import annotations

import logging
import shutil

from app.models.result_models import OperationResult
from app.utils.file_utils import AppPaths
from app.utils.process_utils import run_streaming_command


class IperfService:
    DOWNLOAD_URL = "https://github.com/esnet/iperf/releases"

    def __init__(self, paths: AppPaths, logger: logging.Logger) -> None:
        self.paths = paths
        self.logger = logger

    def executable_details(self) -> tuple[str | None, str]:
        bundled = self.paths.root / "iperf3.exe"
        if bundled.exists():
            return str(bundled), "program folder"

        system_path = shutil.which("iperf3.exe") or shutil.which("iperf3")
        if system_path:
            return system_path, "system PATH"

        return None, ""

    def executable_path(self) -> str | None:
        path, _source = self.executable_details()
        return path

    def is_available(self) -> bool:
        return self.executable_path() is not None

    def run_test(
        self,
        mode: str,
        server: str,
        port: int,
        streams: int,
        duration: int,
        reverse: bool = False,
        progress_callback=None,
        cancel_event=None,
    ) -> OperationResult:
        executable = self.executable_path()
        if not executable:
            return OperationResult(
                False,
                "iperf3 실행 파일을 찾지 못했습니다.",
                (
                    f"{self.paths.root} 폴더에 iperf3.exe를 넣거나 시스템 PATH에서 "
                    "iperf3 / iperf3.exe를 찾을 수 있어야 합니다.\n"
                    f"다운로드: {self.DOWNLOAD_URL}"
                ),
            )

        mode = mode.strip().lower()
        if mode == "server":
            command = [executable, "-s", "-p", str(port), "--forceflush"]
            timeout = 86400
        else:
            if not server.strip():
                return OperationResult(False, "클라이언트 모드에서는 서버 주소가 필요합니다.")
            command = [
                executable,
                "-c",
                server.strip(),
                "-p",
                str(port),
                "-P",
                str(streams),
                "-t",
                str(duration),
                "--forceflush",
            ]
            if reverse:
                command.append("-R")
            timeout = max(duration + 30, 60)

        return run_streaming_command(
            command,
            timeout=timeout,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )
