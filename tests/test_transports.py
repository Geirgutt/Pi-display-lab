"""Tester at browser og fremtidig ESP32 mottar samme type melding."""

import json
import unittest

from transports import BrowserTransport, Esp32Transport, TransportHub


class TransportTests(unittest.TestCase):
    def test_hub_publishes_to_browser_and_enabled_esp32_stub(self) -> None:
        browser = BrowserTransport()
        esp32 = Esp32Transport(enabled=True)
        hub = TransportHub([browser, esp32])
        payload = {"protocol_version": 1, "screen": "home", "message": "Ready"}

        hub.publish(payload)

        self.assertEqual(browser.latest(), payload)
        self.assertEqual(json.loads(esp32.last_encoded or "{}"), payload)


if __name__ == "__main__":
    unittest.main()
