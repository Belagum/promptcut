import json
import tempfile
import unittest
from pathlib import Path

from common import CFG, make_media, sample_plan

import pc_timeline
from pc_common import ffprobe_duration


class TimelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pc_tl_"))
        cls.media = make_media(cls.tmp / "media")
        cls.plan = sample_plan(cls.media)
        cls.tl = pc_timeline.from_plan(cls.plan, cls.tmp, cfg=CFG)

    def track(self, name):
        return next(t for t in self.tl["tracks"] if t["name"] == name)

    def test_shots_contiguous(self):
        clips = self.track("Shots")["clips"]
        self.assertEqual(len(clips), 4)
        for a, b in zip(clips, clips[1:]):
            self.assertAlmostEqual(a["start"] + a["duration"], b["start"], places=3)
        self.assertAlmostEqual(clips[-1]["start"] + clips[-1]["duration"], self.tl["duration"], places=3)

    def test_transitions_follow_plan(self):
        clips = self.track("Shots")["clips"]
        self.assertEqual(clips[0]["transition"], {"type": "dissolve", "duration": 0.4})
        self.assertIn("transition", clips[2])
        self.assertNotIn("transition", clips[3])

    def test_group_voice_is_whole_file(self):
        vo = self.track("VO")["clips"]
        self.assertEqual([c["id"] for c in vo], ["s1_vo", "s2_vo"])
        self.assertAlmostEqual(vo[1]["duration"], ffprobe_duration(self.media["vo"], CFG), places=2)
        self.assertAlmostEqual(vo[1]["start"], self.plan["shots"][1]["vo_start"], places=3)

    def test_footage_clip(self):
        c = self.track("Shots")["clips"][3]
        self.assertEqual(c["kind"], "video")
        self.assertEqual(c["source_in"], 0.5)
        self.assertNotIn("motion", c)
        self.assertEqual(c["media"]["width"], 640)

    def test_music_tiles_and_ducks(self):
        music = self.track("Music")["clips"]
        self.assertEqual(len(music), 3)
        self.assertEqual(music[0]["fade_in"], 1.2)
        self.assertNotIn("fade_out", music[0])
        self.assertEqual(music[-1]["fade_out"], 1.0)
        levels = music[0]["levels"]
        self.assertEqual(levels[0], [0.0, 0.0])
        self.assertIn(-12.0, [db for _, db in levels])
        self.assertAlmostEqual(sum(c["duration"] for c in music), self.tl["duration"], places=3)

    def test_sfx(self):
        sfx = self.track("SFX")["clips"]
        self.assertEqual(len(sfx), 1)
        self.assertEqual(sfx[0]["gain_db"], -8.0)
        self.assertAlmostEqual(sfx[0]["duration"], 0.5, places=2)

    def test_titles_markers_srt(self):
        titles = self.track("Titles")["clips"]
        self.assertEqual(len(titles), 1)
        self.assertTrue(Path(titles[0]["file"]).exists())
        self.assertEqual(titles[0]["media"]["width"], 1920)
        self.assertEqual(len(titles[0]["opacity"]), 4)
        self.assertEqual(len(self.tl["markers"]), 4)
        self.assertTrue(Path(self.tl["subtitles"]["srt"]).exists())
        self.assertTrue((self.tmp / "export" / "timeline.json").exists())

    def test_motion_path(self):
        zoom = pc_timeline.motion_path({"kind": "zoom_in", "amp": 0.5, "focus": [0.8, 0.5]}, 2.0)
        self.assertEqual(len(zoom), 2)
        self.assertEqual(zoom[0][1], 1.0)
        self.assertEqual(zoom[-1][1], 1.5)
        self.assertGreater(zoom[-1][2], 0.5)
        self.assertLessEqual(zoom[-1][2] + 0.5 / zoom[-1][1], 1.0 + 1e-5)
        pan = pc_timeline.motion_path({"kind": "pan_right", "amp": 0.2, "ease": True}, 3.0)
        self.assertEqual(len(pan), 6)
        self.assertLess(pan[0][2], pan[-1][2])
        self.assertEqual(pan[-1][0], 3.0)
        still = pc_timeline.motion_path({"kind": "still"}, 1.0)
        self.assertEqual(still, [(0.0, 1.0, 0.5, 0.5), (1.0, 1.0, 0.5, 0.5)])

    def test_window_rect_covers_canvas(self):
        clip = {"media": {"width": 900, "height": 1600}}
        left, top, ww, wh = pc_timeline.window_rect(clip, (1920, 1080), 1.0, 0.5, 0.5)
        self.assertAlmostEqual(ww / wh, 1920 / 1080, places=6)
        self.assertEqual((left, ww), (0.0, 900.0))
        self.assertAlmostEqual(top, (1600 - 900 * 1080 / 1920) / 2, places=6)

    def test_duck_levels_merge(self):
        lv = pc_timeline.duck_levels([(1.0, 2.0), (2.3, 3.0), (6.0, 7.0)], 10.0)
        self.assertEqual(lv, [[0.85, 0.0], [1.0, -12.0], [3.0, -12.0], [3.4, 0.0],
                              [5.85, 0.0], [6.0, -12.0], [7.0, -12.0], [7.4, 0.0]])
        self.assertEqual(pc_timeline.slice_levels(lv, 2.0, 3.2), [[0.0, -12.0], [1.0, -12.0], [1.2, -6.0]])

    def test_cover_focus(self):
        self.assertEqual(pc_timeline.cover_focus([0.5, 0.5], 1600, 900, 1080, 1920), [0.5, 0.5])
        self.assertEqual(pc_timeline.cover_focus([0.9, 0.5], 1600, 900, 1080, 1920), [1.0, 0.5])
        self.assertEqual(pc_timeline.cover_focus("0.25,0.5", 1600, 900, 1920, 1080), [0.25, 0.5])
        self.assertIsNone(pc_timeline.cover_focus(None, 1, 1, 1, 1))

    def test_load_spec_hydrates(self):
        spec = {"name": "hand", "size": [1080, 1920], "fps": 30, "tracks": [
            {"type": "video", "name": "Shots", "clips": [
                {"file": self.media["tall"], "start": 0, "duration": 2,
                 "motion": {"kind": "zoom_in", "amp": 0.2}}]},
            {"type": "audio", "name": "VO", "clips": [
                {"file": self.media["vo"], "start": 0.2, "duration": 1.0}]}]}
        p = self.tmp / "hand.json"
        p.write_text(json.dumps(spec), encoding="utf-8")
        tl = pc_timeline.load_spec(p, CFG)
        clip = tl["tracks"][0]["clips"][0]
        self.assertEqual(clip["kind"], "image")
        self.assertEqual(clip["media"]["width"], 900)
        self.assertEqual(tl["duration"], 2.0)
        self.assertEqual(tl["tracks"][1]["clips"][0]["media"]["channels"], 1)

    def test_validate_reports_problems(self):
        spec = {"tracks": [{"type": "video", "clips": [
            {"file": self.media["wide"], "start": 0, "duration": 2},
            {"file": self.media["wide"], "start": 1, "duration": 2},
            {"file": str(self.tmp / "missing.png"), "start": 5, "duration": 0}]}]}
        errs = pc_timeline.validate(spec)
        self.assertTrue(any("overlaps" in e for e in errs))
        self.assertTrue(any("not found" in e for e in errs))
        self.assertTrue(any("positive" in e for e in errs))
        self.assertEqual(pc_timeline.validate({"tracks": []}), ["timeline has no tracks"])


if __name__ == "__main__":
    unittest.main()
