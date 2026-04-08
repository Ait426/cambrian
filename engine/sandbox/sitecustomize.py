"""Cambrian sandbox bootstrap. PYTHONPATH에 포함되면 서브프로세스 시작 시 자동 실행."""
import builtins
import os

if os.environ.get("CAMBRIAN_BLOCK_NETWORK"):
    import socket as _socket

    def _blocked_connect(self, address):
        raise OSError("Network access blocked by Cambrian sandbox")

    def _blocked_connect_ex(self, address):
        raise OSError("Network access blocked by Cambrian sandbox")

    def _blocked_create_connection(*args, **kwargs):
        raise OSError("Network access blocked by Cambrian sandbox")

    _socket.socket.connect = _blocked_connect
    _socket.socket.connect_ex = _blocked_connect_ex
    _socket.create_connection = _blocked_create_connection

if os.environ.get("CAMBRIAN_BLOCK_FILESYSTEM"):
    import io as _io
    import pathlib as _pathlib
    import sys as _sys

    _work_dir = os.path.realpath(os.environ.get("CAMBRIAN_WORK_DIR", ""))
    _python_prefix = os.path.realpath(_sys.prefix)

    def _is_allowed(path_str):
        """경로가 허용 범위 안인지 판정한다. realpath 기반으로 symlink/.. 우회를 차단."""
        try:
            real = os.path.realpath(os.path.abspath(str(path_str)))
            # os.path.commonpath 기반 비교: 정확한 디렉토리 경계 판정
            if _work_dir:
                try:
                    os.path.commonpath([real, _work_dir])
                    if real == _work_dir or real.startswith(_work_dir + os.sep):
                        return True
                except ValueError:
                    pass
            try:
                os.path.commonpath([real, _python_prefix])
                if real == _python_prefix or real.startswith(_python_prefix + os.sep):
                    return True
            except ValueError:
                pass
            return False
        except Exception:
            # 경로 해석 실패 시 안전하게 허용 (import 깨짐 방지)
            return True

    def _guard(path_str):
        """허용 범위 밖 경로 접근 시 PermissionError를 발생시킨다."""
        if not _is_allowed(path_str):
            raise PermissionError(f"Filesystem access blocked by Cambrian: {path_str}")

    # --- builtins.open 패치 ---
    _orig_open = builtins.open

    def _restricted_open(file, *args, **kwargs):
        _guard(file)
        return _orig_open(file, *args, **kwargs)

    builtins.open = _restricted_open

    # --- io.open 패치 ---
    _orig_io_open = _io.open

    def _restricted_io_open(file, *args, **kwargs):
        _guard(file)
        return _orig_io_open(file, *args, **kwargs)

    _io.open = _restricted_io_open

    # --- os.open 패치 ---
    _orig_os_open = os.open

    def _restricted_os_open(path, flags, mode=0o777, *, dir_fd=None):
        _guard(path)
        return _orig_os_open(path, flags, mode, dir_fd=dir_fd)

    os.open = _restricted_os_open

    # --- pathlib.Path 메서드 패치 ---
    _orig_path_open = _pathlib.Path.open
    _orig_path_read_text = _pathlib.Path.read_text
    _orig_path_read_bytes = _pathlib.Path.read_bytes
    _orig_path_write_text = _pathlib.Path.write_text
    _orig_path_write_bytes = _pathlib.Path.write_bytes

    def _restricted_path_open(self, *args, **kwargs):
        _guard(self)
        return _orig_path_open(self, *args, **kwargs)

    def _restricted_path_read_text(self, *args, **kwargs):
        _guard(self)
        return _orig_path_read_text(self, *args, **kwargs)

    def _restricted_path_read_bytes(self):
        _guard(self)
        return _orig_path_read_bytes(self)

    def _restricted_path_write_text(self, *args, **kwargs):
        _guard(self)
        return _orig_path_write_text(self, *args, **kwargs)

    def _restricted_path_write_bytes(self, data):
        _guard(self)
        return _orig_path_write_bytes(self, data)

    _pathlib.Path.open = _restricted_path_open
    _pathlib.Path.read_text = _restricted_path_read_text
    _pathlib.Path.read_bytes = _restricted_path_read_bytes
    _pathlib.Path.write_text = _restricted_path_write_text
    _pathlib.Path.write_bytes = _restricted_path_write_bytes
