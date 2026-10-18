import struct
import unittest
from listen import MAGIC, MEDIA_MAGIC, Parser, checksum, mic_frame, downsample, call_playback


def frame(sequence=1, pcm=b"\x0a\x00\xff\x7f"):
    fields = struct.pack("<HHI", len(pcm), 16000, sequence)
    return MAGIC + fields + struct.pack("<I", checksum(fields + pcm)) + pcm


class ProtocolTests(unittest.TestCase):
    def test_interleaved_media_and_call_with_fragmentation(self):
        # SBC payloads may have odd length and span multiple serial packets.
        pcm = b"\x9c\x11\x22"
        fields = struct.pack("<HHI", len(pcm), 0, 8)
        media = MEDIA_MAGIC + fields + struct.pack("<I", checksum(fields + pcm)) + pcm
        data = frame(7) + b"log\r\n" + media + frame(9)
        parser = Parser()
        result = []
        for i in range(0, len(data), 5):
            result.extend(parser.feed(data[i:i + 5]))
        self.assertEqual([(r, s) for r, s, _ in result], [(16000, 7), (0, 8), (16000, 9)])
        self.assertEqual(result[1][2], pcm)

    def test_media_corruption_resynchronizes_to_call(self):
        fields = struct.pack("<HHI", 3, 0, 1)
        media = MEDIA_MAGIC + fields + struct.pack("<I", 0) + b"abc"
        parser = Parser()
        self.assertEqual([s for _, s, _ in parser.feed(media + frame(2))], [2])
        self.assertEqual(parser.bad, 1)

    def test_call_playback_preserves_samples_in_both_channels(self):
        pcm = struct.pack("<hh", 1234, -5678)
        for rate in (8000, 16000):
            out = call_playback(pcm, rate)
            samples = struct.unpack("<" + "h" * (len(out) // 2), out)
            factor = 48000 // rate
            self.assertEqual(samples, tuple([1234] * (factor * 2) + [-5678] * (factor * 2)))

    def test_fragmented_frames_and_text(self):
        data = b"boot log\r\n" + frame() + b"log\n" + frame(2)
        parser = Parser()
        result = []
        for byte in data:
            result.extend(parser.feed(bytes([byte])))
        self.assertEqual([r[1] for r in result], [1, 2])
        self.assertEqual(result[0][2], b"\x0a\x00\xff\x7f")

    def test_recovers_after_corrupt_payload(self):
        broken = bytearray(frame())
        broken[-1] ^= 1
        parser = Parser()
        self.assertEqual([r[1] for r in parser.feed(broken + frame(3))], [3])
        self.assertEqual(parser.bad, 1)


class MicrophoneTests(unittest.TestCase):
    def test_microphone_frame(self):
        pcm = struct.pack("<hhh", -32768, 0, 32767)
        packet = mic_frame(pcm, 8000, 0x100000001)
        self.assertEqual(packet[:8], b"PBMIC01!")
        self.assertEqual(struct.unpack_from("<HHI", packet, 8), (6, 8000, 1))
        self.assertEqual(struct.unpack_from("<I", packet, 16)[0],
                         checksum(packet[8:16] + pcm))
        self.assertEqual(packet[20:], pcm)

    def test_downsample_both_call_rates(self):
        for rate, factor in ((8000, 6), (16000, 3)):
            pcm = struct.pack("<" + "h" * (factor * 2),
                              *([1200] * factor + [-600] * factor))
            self.assertEqual(downsample(pcm, rate), struct.pack("<hh", 1200, -600))

    def test_stereo_microphone_mixed_to_mono(self):
        pcm = struct.pack("<" + "h" * 6, *([1000, 3000] * 3))
        self.assertEqual(downsample(pcm, 16000, channels=2), struct.pack("<h", 2000))

    def test_gain_clips_without_wrapping(self):
        pcm = struct.pack("<hhhhhh", 20000, 20000, 20000, -20000, -20000, -20000)
        self.assertEqual(downsample(pcm, 16000, 2), struct.pack("<hh", 32767, -32768))


if __name__ == "__main__":
    unittest.main()
