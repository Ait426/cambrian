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
    import sys as _sys
    _work_dir = os.path.abspath(os.environ.get("CAMBRIAN_WORK_DIR", ""))
    _python_prefix = os.path.abspath(_sys.prefix)
    _orig_open = builtins.open

    def _restricted_open(file, *args, **kwargs):
        try:
            abs_path = os.path.abspath(str(file))
            allowed = (
                abs_path.startswith(_work_dir)
                or abs_path.startswith(_python_prefix)
            )
            if not allowed:
                raise PermissionError(f"Filesystem access blocked by Cambrian: {file}")
        except PermissionError:
            raise
        except Exception:
            pass
        return _orig_open(file, *args, **kwargs)

    builtins.open = _restricted_open
