import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from common import CFG, make_media, sample_plan

import pc_timeline
import pc_xmeml


def param(item, pid):
    return next((p for p in item.findall("filter/effect/parameter") if p.findtext("parameterid") == pid), None)


class XmemlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pc_xml_"))
        cls.media = make_media(cls.tmp / "media")
        cls.tl = pc_timeline.from_plan(sample_plan(cls.media), cls.tmp, cfg=CFG)
        cls.fps = cls.tl["fps"]
        cls.roots = {}
        for prof in pc_xmeml.PROFILES:
            path = cls.tmp / f"t.{prof}.xml"
            pc_xmeml.write(cls.tl, path, prof)
            cls.roots[prof] = ET.parse(path).getroot()

    def seq(self, prof="premiere"):
        return self.roots[prof].find("sequence")

    def shots(self, prof="premiere"):
        return self.seq(prof).findall("media/video/track")[0].findall("clipitem")

    def test_header(self):
        self.assertEqual(self.roots["premiere"].get("version"), "5")
        seq = self.seq()
        self.assertEqual(int(seq.findtext("duration")), round(self.tl["duration"] * self.fps))
        fmt = seq.find("media/video/format/samplecharacteristics")
        self.assertEqual((fmt.findtext("width"), fmt.findtext("height")), ("1920", "1080"))
        self.assertEqual(seq.findtext("rate/timebase"), "30")
        text = (self.tmp / "t.premiere.xml").read_text(encoding="utf-8")
        self.assertTrue(text.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>'))

    def test_transitions_use_minus_one_convention(self):
        track = list(self.seq().findall("media/video/track")[0])
        items = [e for e in track if e.tag == "clipitem"]
        trans = [e for e in track if e.tag == "transitionitem"]
        self.assertEqual((len(items), len(trans)), (4, 3))
        for i, el in enumerate(track):
            if el.tag != "transitionitem":
                continue
            self.assertEqual(el.findtext("alignment"), "start")
            self.assertEqual(el.findtext("effect/name"), "Cross Dissolve")
            self.assertEqual(track[i - 1].findtext("end"), "-1")
            self.assertEqual(track[i + 1].findtext("start"), "-1")
            self.assertEqual(int(el.findtext("end")) - int(el.findtext("start")), round(0.4 * self.fps))
        first = items[0]
        self.assertEqual((first.findtext("start"), first.findtext("in")), ("0", "0"))
        self.assertEqual(int(first.findtext("out")), round((2.1 + 0.4) * self.fps))
        self.assertEqual(first.findtext("stillframe"), "TRUE")
        self.assertEqual(items[-1].findtext("end"), str(round(self.tl["duration"] * self.fps)))

    def test_footage_in_out(self):
        foot = self.shots()[3]
        self.assertEqual(int(foot.findtext("in")), round(0.5 * self.fps))
        self.assertIsNone(foot.find("stillframe"))
        self.assertEqual(int(foot.findtext("duration")), round(2.0 * self.fps))
        self.assertEqual(int(foot.findtext("out")), round(2.0 * self.fps))
        self.assertEqual(param(foot, "scale").findtext("value"), "300")
        self.assertEqual(param(self.shots("resolve")[3], "scale").findtext("value"), "100")

    def test_pathurl(self):
        urls = [e.text for e in self.seq().iter("pathurl")]
        self.assertTrue(urls)
        for u in urls:
            self.assertTrue(u.startswith("file://localhost/"))
            self.assertNotIn("\\", u)
            self.assertNotIn(" ", u)

    def test_motion_keyframes(self):
        first = self.shots()[0]
        scale, center = param(first, "scale"), param(first, "center")
        kfs = scale.findall("keyframe")
        self.assertEqual(len(kfs), 6)
        whens = [int(k.findtext("when")) for k in kfs]
        self.assertEqual(whens[0], int(first.findtext("in")))
        self.assertEqual(whens[-1], int(first.findtext("out")))
        self.assertAlmostEqual(float(kfs[0].findtext("value")), 120.0, places=2)
        self.assertAlmostEqual(float(kfs[-1].findtext("value")), 120.0 * 1.12, places=2)
        horiz = [float(k.findtext("value/horiz")) for k in center.findall("keyframe")]
        self.assertEqual(horiz[0], 0.0)
        self.assertLess(horiz[-1], 0.0)
        self.assertEqual(param(first, "rotation").findtext("value"), "0")

    def test_resolve_profile_scales_relative_to_fit(self):
        scale = param(self.shots("resolve")[0], "scale")
        self.assertAlmostEqual(float(scale.find("keyframe").findtext("value")), 100.0, places=2)
        tall = param(self.shots("resolve")[1], "scale")
        self.assertIsNone(tall.find("keyframe"))
        self.assertAlmostEqual(float(tall.findtext("value")), 100 * (1920 / (900 / 1.12)) / min(1920 / 900, 1080 / 1600),
                               places=1)
        center = param(self.shots("resolve")[1], "center")
        horiz = [float(k.findtext("value/horiz")) for k in center.findall("keyframe")]
        self.assertEqual(len(horiz), 2)
        self.assertGreater(horiz[0], horiz[1])

    def test_title_track(self):
        titles = self.seq().findall("media/video/track")[1].findall("clipitem")
        self.assertEqual(len(titles), 1)
        self.assertEqual(titles[0].findtext("alphatype"), "straight")
        vals = [float(k.findtext("value")) for k in param(titles[0], "opacity").findall("keyframe")]
        self.assertEqual(vals, [0.0, 100.0, 100.0, 0.0])
        self.assertIsNone(param(titles[0], "scale"))

    def test_audio_tracks(self):
        tracks = self.seq().findall("media/audio/track")
        self.assertEqual(len(tracks), 5)
        vo = tracks[0].findall("clipitem")
        self.assertEqual(len(vo), 2)
        self.assertEqual(vo[0].findtext("sourcetrack/trackindex"), "1")
        self.assertEqual(param(vo[0], "level").findtext("value"), "1")
        self.assertEqual(int(vo[0].findtext("start")), round(0.15 * self.fps))
        left, right = tracks[1].findall("clipitem"), tracks[2].findall("clipitem")
        self.assertEqual((len(left), len(right)), (3, 3))
        self.assertEqual(right[0].findtext("sourcetrack/trackindex"), "2")
        refs = [l.findtext("linkclipref") for l in left[0].findall("link")]
        self.assertIn(right[0].get("id"), refs)
        self.assertIn(left[0].get("id"), refs)
        self.assertEqual(tracks[2].findtext("outputchannelindex"), "2")
        kfs = param(left[0], "level").findall("keyframe")
        vals = [float(k.findtext("value")) for k in kfs]
        self.assertEqual(vals[0], 0.0)
        self.assertTrue(any(abs(v - 10 ** (-32 / 20)) < 1e-4 for v in vals))
        self.assertEqual(float(param(tracks[3].find("clipitem"), "level").findtext("value")),
                         round(10 ** (-8 / 20), 6))

    def test_markers(self):
        markers = self.seq().findall("marker")
        self.assertEqual([m.findtext("name") for m in markers], ["s1", "s2", "s3", "s4"])
        self.assertEqual(markers[0].findtext("out"), "-1")

    def test_unknown_profile(self):
        with self.assertRaises(ValueError):
            pc_xmeml.write(self.tl, self.tmp / "x.xml", "avid")


if __name__ == "__main__":
    unittest.main()
