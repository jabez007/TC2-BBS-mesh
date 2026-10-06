import threading
import time
import unittest

from radio_drivers import DriverClosedError, MeshtasticDriver


class FakeMyInfo:
    my_node_id = "!local"
    my_node_num = 123


class BlockingInterface:
    def __init__(self):
        self.myInfo = FakeMyInfo()
        self.nodes = {
            "!local": {"num": 123, "user": {"shortName": "Local"}},
            "!peer": {"num": 456, "user": {"shortName": "Peer"}},
        }
        self.started_send = threading.Event()
        self.allow_send_to_finish = threading.Event()
        self.closed = threading.Event()
        self.close_calls = 0

    def sendText(self, text, destinationId, wantAck, wantResponse):
        self.started_send.set()
        self.allow_send_to_finish.wait(timeout=2)
        return {"text": text, "destinationId": destinationId}

    def getNode(self, node_id):
        return self.nodes.get(node_id)

    def close(self):
        self.close_calls += 1
        self.closed.set()
        return True


class MeshtasticDriverLifecycleTests(unittest.TestCase):
    def test_close_waits_for_active_call_and_fences_new_calls(self):
        interface = BlockingInterface()
        driver = MeshtasticDriver(interface)
        send_finished = threading.Event()

        def do_send():
            try:
                driver.send_text("hello", "!peer")
            finally:
                send_finished.set()

        send_thread = threading.Thread(target=do_send)
        send_thread.start()
        self.assertTrue(interface.started_send.wait(timeout=1), "send never started")

        close_thread = threading.Thread(target=driver.close)
        close_thread.start()

        deadline = time.time() + 1
        while time.time() < deadline:
            if self._driver_is_closing(driver):
                break
            time.sleep(0.01)
        self.assertTrue(self._driver_is_closing(driver), "driver never entered closing state")
        self.assertFalse(interface.closed.is_set(), "driver closed before in-flight call finished")

        with self.assertRaises(DriverClosedError):
            driver.getNode("!peer")

        interface.allow_send_to_finish.set()
        send_thread.join(timeout=1)
        close_thread.join(timeout=1)

        self.assertTrue(send_finished.is_set(), "send thread did not finish")
        self.assertTrue(interface.closed.is_set(), "interface.close() was not called")
        self.assertEqual(interface.close_calls, 1)

        with self.assertRaises(DriverClosedError):
            driver.send_text("after close", "!peer")

    @staticmethod
    def _driver_is_closing(driver):
        with driver._lifecycle:
            return driver._closing


if __name__ == "__main__":
    unittest.main()
