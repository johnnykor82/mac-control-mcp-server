"""Stable-derived GUI IPC recovery in independent Mac Control DEV."""
from __future__ import annotations
import errno
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock

from mac_control.legacy_handlers import gui_ipc_recovery as ipc
from mac_control.legacy_handlers import gui_ops


class GUIIPCReliabilityTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dev-gui-ipc-fixture-")
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.socket_path = self.base / "gui.sock"
        self.helper = self.base / "MacControlGUIDev.app" / "Contents" / "MacOS" / "MacControlGUIDev"
        self.helper.parent.mkdir(parents=True)
        self.helper.write_text("test helper fixture")

    def listen(self):
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        server.listen(2)
        self.addCleanup(server.close)
        return server

    def test_alive_socket_connects_without_spawning_helper(self):
        listener = self.listen()
        with mock.patch.object(ipc.subprocess, "run") as launch:
            connection = ipc.connect(self.socket_path, self.helper, 2)
            connection.close()
            launch.assert_not_called()
        listener.accept()[0].close()

    def test_stale_socket_automatically_recovers_before_dispatch(self):
        dead = self.listen()
        dead.close()
        listeners = []

        def start_fixture(*_args, **_kwargs):
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(self.socket_path))
            listener.listen(2)
            listeners.append(listener)
            return mock.Mock(returncode=0, stderr="")

        with mock.patch.object(ipc, "_stop_broken_helper") as stop, \
             mock.patch.object(ipc.subprocess, "run", side_effect=start_fixture):
            connection = ipc.connect(self.socket_path, self.helper, 2)
            connection.close()
            stop.assert_called_once()
        listeners[0].accept()[0].close()
        listeners[0].close()

    def test_portable_product_launch_receives_the_endpoint_data_root(self):
        helper = self.helper.with_name("MacControlMCPServer")
        helper.write_text("portable fixture")
        endpoint = self.base / "run/maccontrol-gui.sock"
        endpoint.parent.mkdir()
        missing = FileNotFoundError(errno.ENOENT, "not started")
        connection = mock.Mock()
        with mock.patch.object(ipc, "_once", side_effect=[missing, missing, connection]), \
             mock.patch.object(ipc, "_stop_broken_helper"), \
             mock.patch.object(ipc, "_discard_stale_socket"), \
             mock.patch.object(ipc.subprocess, "run", return_value=mock.Mock(returncode=0)) as launch:
            self.assertIs(ipc.connect(endpoint, helper, 2), connection)
        self.assertEqual(launch.call_args.args[0][-4:],
                         ["--args", "--serve", "--data-root", str(self.base)])

    def test_unsafe_regular_file_never_deleted(self):
        self.socket_path.write_text("private data")
        with mock.patch.object(ipc, "_stop_broken_helper"):
            with self.assertRaises(ipc.GUIIPCError):
                ipc.connect(self.socket_path, self.helper, 1)
        self.assertEqual(self.socket_path.read_text(), "private data")

    def test_write_sent_once_even_if_response_connection_breaks(self):
        class Disconnected:
            sends = 0

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def sendall(self, value):
                self.sends += 1

            def shutdown(self, *_):
                pass

            def recv(self, *_):
                raise ConnectionResetError(errno.ECONNRESET, "closed after action")

        connection = Disconnected()
        with mock.patch.object(gui_ops, "HELPER", self.helper), \
             mock.patch.object(ipc, "connect", return_value=connection):
            with self.assertRaises(ipc.GUIIPCError) as failure:
                gui_ops._call("mouse", action="left_click", x=20, y=30)
        self.assertEqual(failure.exception.code, "connection_lost")
        self.assertEqual(connection.sends, 1)


if __name__ == "__main__":
    unittest.main()
