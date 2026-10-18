import copy
import json
import struct
import unittest
from unittest.mock import patch

from listen import Parser, MEDIA_MAGIC, checksum, FirmwareLog
from phone_control import command_frame, decode_status


STATUS = dict(v=1, ready=True, selected="AA:BB:CC:DD:EE:FF", hfp=True,
              a2dp=False, call=False, pairing=60, message="Pairing open",
              phones=[dict(address="AA:BB:CC:DD:EE:FF", name="My phone")])


def status_frame(value):
    payload = json.dumps(value).encode()
    fields = struct.pack("<HHI", len(payload), 0, 0)
    return b"PBCTL01!" + fields + struct.pack("<I", checksum(fields + payload)) + payload


class ControlTests(unittest.TestCase):
    def test_firmware_logs_survive_fragmentation_without_logging_audio_payloads(self):
        parser = Parser(on_noise=FirmwareLog())
        payload = b"I (999) NOT_A_LOG: private audio bytes\n"
        fields = struct.pack("<HHI", len(payload), 0, 7)
        media = MEDIA_MAGIC + fields + struct.pack("<I", checksum(fields + payload)) + payload
        wire = b"\x1b[0;32mI (123) BT_MEDIA: A2DP audio state: 2\x1b[0m\r\n" + media
        with patch("listen.logging.info") as log:
            packets = []
            for offset in range(0, len(wire), 3):
                packets.extend(parser.feed(wire[offset:offset + 3]))
        self.assertEqual(packets, [(0, 7, payload)])
        log.assert_called_once_with("ESP32: %s", "I (123) BT_MEDIA: A2DP audio state: 2")
    def test_commands_have_fixed_layout_and_bound_approval_to_request(self):
        frame = command_frame(dict(cmd="approve", address="AA:BB:CC:DD:EE:FF", challenge=123))
        packets = list(Parser().feed(frame))
        self.assertEqual(packets, [(-1, 0, struct.pack("<BB6sI", 4, 0, bytes.fromhex("AABBCCDDEEFF"), 123))])
        with self.assertRaises(ValueError):
            command_frame(dict(cmd="select", address="not an address"))

    def test_fragmented_status_and_media_stay_separate(self):
        payload = b"\x9c\x10\x11"
        fields = struct.pack("<HHI", len(payload), 0, 7)
        media = MEDIA_MAGIC + fields + struct.pack("<I", checksum(fields + payload)) + payload
        data = b"firmware log\n" + status_frame(STATUS) + media
        parser = Parser()
        packets = []
        for index in range(0, len(data), 7):
            packets.extend(parser.feed(data[index:index + 7]))
        self.assertEqual(decode_status(packets[0][2]), STATUS)
        self.assertEqual(packets[1], (0, 7, payload))

    def test_corrupted_control_frame_is_rejected_and_parser_recovers(self):
        bad = bytearray(status_frame(STATUS))
        bad[-1] ^= 1
        parser = Parser()
        packets = list(parser.feed(bad + status_frame(STATUS)))
        self.assertEqual(len(packets), 1)
        self.assertEqual(decode_status(packets[0][2]), STATUS)
        self.assertEqual(parser.bad, 1)

    def test_malformed_or_unsupported_status_cannot_enable_controls(self):
        for key, value in [("v", 2), ("pairing", -1), ("pairing", 61), ("pairing", True),
                           ("phones", [{}]), ("selected", 12), ("ready", "true"),
                           ("pending", dict(address="AA:BB:CC:DD:EE:FF", number=1000000))]:
            malformed = copy.deepcopy(STATUS)
            malformed[key] = value
            self.assertIsNone(decode_status(json.dumps(malformed).encode()), key)
        self.assertIsNone(decode_status(b"not json"))


if __name__ == "__main__":
    unittest.main()
