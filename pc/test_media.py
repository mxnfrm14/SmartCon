"""End-to-end codec checks; require the optional runtime dependency PyAV."""
import unittest

try:
    import av
except ImportError:
    av = None

from listen import MediaDecoder


@unittest.skipIf(av is None, "PyAV non installe : installer pc/requirements.txt")
class MediaTests(unittest.TestCase):
    def test_sbc_fragmented_stream_decodes_both_rates_to_stereo_48k(self):
        for rate in (44100, 48000):
            with self.subTest(rate=rate):
                encoder = av.CodecContext.create("sbc", "w")
                encoder.sample_rate = rate
                encoder.layout = "stereo"
                encoder.format = "s16"
                encoder.bit_rate = 328000
                encoder.open()
                encoded = bytearray()
                for _ in range(24):
                    frame = av.AudioFrame(format="s16", layout="stereo",
                                          samples=encoder.frame_size)
                    frame.sample_rate = rate
                    frame.planes[0].update(bytes(frame.planes[0].buffer_size))
                    for packet in encoder.encode(frame):
                        encoded.extend(bytes(packet))
                for packet in encoder.encode(None):
                    encoded.extend(bytes(packet))
                self.assertTrue(encoded)
                decoder = MediaDecoder()
                output = bytearray()
                # Deliberately split SBC headers and frames across serial payloads.
                for i in range(0, len(encoded), 137):
                    output.extend(decoder.feed(encoded[i:i + 137]))
                self.assertGreater(len(output), 8000)
                self.assertEqual(len(output) % 4, 0)
                self.assertEqual(decoder.resampler.rate, 48000)
                self.assertEqual(decoder.resampler.layout.name, "stereo")
