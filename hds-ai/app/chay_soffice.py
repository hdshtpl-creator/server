"""chay_soffice.py — gọi LibreOffice mà không để lại tiến trình mồ côi.

`/usr/bin/libreoffice` là script → `oosplash` → `soffice.bin`. Khi quá giờ,
`subprocess.run(timeout=)` chỉ giết tiến trình con TRỰC TIẾP; `soffice.bin` là
cháu nên sống tiếp, cha thành init và quay 100% CPU mãi mãi. 07/10/2026 máy chủ
có hai tiến trình như vậy chạy liền 7 ngày 10 giờ (hai tệp .doc của lượt
`--thu-lai-loi` 29/09), mỗi cái ăn trọn một nhân.

Cách chữa: cho LibreOffice một PHIÊN riêng (`start_new_session`) rồi khi quá
giờ giết cả NHÓM tiến trình — gom được cả cháu.
"""
from __future__ import annotations

import os
import signal
import subprocess


def _giet_nhom(proc: subprocess.Popen) -> None:
    if os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    else:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def chay(cmd, timeout: float) -> None:
    """Chạy `cmd` (lệnh LibreOffice), bỏ đầu ra. Lỗi như `subprocess.run(check=True)`:
    quá giờ → TimeoutExpired, mã thoát ≠ 0 → CalledProcessError."""
    kw = {"start_new_session": True} if os.name == "posix" else {}
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, **kw)
    try:
        rc = proc.wait(timeout=timeout)
    except BaseException:
        # Quá giờ, hay luồng gọi bị ngắt (Ctrl+C, hệ thống dừng dịch vụ) — đều
        # phải dọn cả nhóm, không thì lại có soffice.bin mồ côi.
        _giet_nhom(proc)
        raise
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd)
