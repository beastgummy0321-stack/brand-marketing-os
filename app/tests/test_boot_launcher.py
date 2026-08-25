# -*- coding: utf-8 -*-
"""app/tests/test_boot_launcher.py — 票 F6：無視窗啟動器的 port 探測邏輯。

只測 `_port_is_listening` 這個純 socket 判斷——`main()` 會真的把 uvicorn 跑起來，
那正是這張票的硬限制不准做的事（見 F6 票／CLAUDE.md：絕不能在測試裡啟動真的 server，
`_auto_sync_if_due` 一活起來就會打外部 API、結算 data/app.db 裡的 B1 演練檔期）。
"""

import socket
import unittest

from app.tools.boot_launcher import _port_is_listening


class PortIsListeningTest(unittest.TestCase):
    def test_true_when_something_is_listening_on_the_port(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        try:
            port = server.getsockname()[1]
            self.assertTrue(_port_is_listening(port))
        finally:
            server.close()

    def test_false_when_nothing_is_listening_on_the_port(self):
        # 借一個當下沒人用的 port 號：先開一個 socket 拿系統配的空號，關掉後短時間內
        # 大機率還是空的——用來確認「沒人聽」那個分支，不必猜死一個固定 port。
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        self.assertFalse(_port_is_listening(port))


if __name__ == "__main__":
    unittest.main()
