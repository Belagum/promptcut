import subprocess
import tempfile
import unittest
from pathlib import Path

from common import CFG, ROOT, make_media, sample_plan

import pc_timeline
import pc_vegas

CSC = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")


class VegasTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pc_veg_"))
        cls.media = make_media(cls.tmp / "media")
        cls.tl = pc_timeline.from_plan(sample_plan(cls.media), cls.tmp, cfg=CFG)
        cls.result = pc_vegas.write(cls.tl, cls.tmp)
        cls.text = Path(cls.result["script"]).read_text(encoding="utf-8-sig")
        cls.lines = cls.text.splitlines()

    def calls(self, prefix):
        return [l for l in self.lines if l.strip().startswith(prefix)]

    def test_script_shape(self):
        self.assertIn("public void FromVegas(Vegas vegas)", self.text)
        self.assertEqual(len(self.calls("Clip(v")), 5)
        self.assertEqual(len(self.calls("Sound(a")), 6)
        self.assertEqual(len(self.calls("Volume(a")), 1)
        self.assertEqual(len(self.calls("Mark(")), 4)
        self.assertIn("p.Video.Width = 1920;", self.text)
        self.assertIn("p.Video.FrameRate = 30.0;", self.text)
        self.assertLess(self.text.index('AddVideo(@"Titles")'), self.text.index('AddVideo(@"Shots")'))
        self.assertTrue(self.text.rstrip().endswith("}"))
        self.assertEqual(self.result["project"], str(self.tmp / "promptcut_test.veg"))
        self.assertIn(f'vegas.SaveProject(@"{self.tmp / "promptcut_test.veg"}");', self.text)

    def test_clip_arguments(self):
        clips = self.calls("Clip(v")
        title, first, footage = clips[0], clips[1], clips[4]
        self.assertIn(", 0.0, 1.0, 0.2, 0.2, null);", title)
        self.assertIn(", 0.0, 2.5, 0.0, 1.0, 0.0, 0.0, new double[] {", first)
        nums = first.split("new double[] {")[1].split("}")[0].split(",")
        self.assertEqual(len(nums), 30)
        self.assertIn(", 0.5, 1.0, 0.0, 0.0, null);", footage)

    def test_volume_envelope(self):
        line = self.calls("Volume(a")[0]
        nums = [float(x) for x in line.split("{")[1].split("}")[0].split(",")]
        times, dbs = nums[0::2], nums[1::2]
        self.assertEqual(times, sorted(times))
        self.assertEqual(len(times), len(set(times)))
        self.assertLessEqual(times[-1], self.tl["duration"] + 1e-6)
        self.assertIn(-12.0, dbs)
        self.assertIn(0.0, dbs)

    def test_playback_rate_clamped(self):
        tl = {"name": "fast", "size": [1920, 1080], "fps": 30, "duration": 1.0, "markers": [],
              "tracks": [{"type": "video", "name": "Shots", "clips": [
                  {"id": "x", "file": self.media["clip"], "kind": "video", "start": 0.0, "duration": 1.0,
                   "source_in": 0.0, "speed": 8.0,
                   "media": {"width": 640, "height": 360, "duration": 2.0}}]}]}
        r = pc_vegas.write(tl, self.tmp / "fast")
        text = Path(r["script"]).read_text(encoding="utf-8-sig")
        self.assertIn(", 0.0, 4.0, 0.0, 0.0, null);", text)

    @unittest.skipUnless(CSC.exists(), "csc.exe not available")
    def test_compiles_against_stub(self):
        out = self.tmp / "script.dll"
        proc = subprocess.run([str(CSC), "-nologo", "-target:library", f"-out:{out}",
                               str(ROOT / "tests" / "stubs" / "ScriptPortal.Vegas.cs"),
                               self.result["script"]], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
