import struct
import subprocess
import unittest
from pathlib import Path
from zipfile import ZipFile


REPOSITORY = Path(__file__).resolve().parents[1]
THEMES = REPOSITORY / "themes"
STATIC_COLOURS = ("green", "orange", "purple", "red")
THEME_VARIANTS = tuple(
    (colour, variant)
    for colour in STATIC_COLOURS
    for variant in ("static", "animated")
) + (("blue", "animated"), ("white", "animated"))


class BlackArchPlymouthPackageTests(unittest.TestCase):
    def test_each_archive_is_a_complete_script_theme(self):
        for colour, variant in THEME_VARIANTS:
            with self.subTest(colour=colour, variant=variant):
                name = f"blackarch-{colour}-{variant}"
                archive_path = THEMES / name / "plymouth" / f"{name}.zip"
                self.assertTrue(archive_path.is_file())

                with ZipFile(archive_path) as archive:
                    entries = set(archive.namelist())
                    definition_path = f"{name}/{name}.plymouth"
                    script_path = f"{name}/{name}.script"
                    self.assertIn(definition_path, entries)
                    definition = archive.read(definition_path).decode()
                    self.assertIn(f"themes/{name}", definition)
                    if variant == "animated":
                        self.assertIn(script_path, entries)
                        self.assertIn(f"{name}/dialog/entry.png", entries)
                        self.assertIn(f"{name}/dialog/lock.png", entries)
                        self.assertIn(f"{name}/dialog/bullet.png", entries)
                        frame_entries = sorted(
                            entry
                            for entry in entries
                            if f"{name}/frames/frame-" in entry
                        )
                        progress_entries = sorted(
                            entry
                            for entry in entries
                            if f"{name}/progress/progress-" in entry
                        )
                        self.assertEqual(96, len(frame_entries))
                        self.assertTrue(
                            frame_entries[0].endswith("frame-000.png")
                        )
                        self.assertTrue(
                            frame_entries[-1].endswith("frame-095.png")
                        )
                        self.assertEqual(51, len(progress_entries))
                        self.assertIn("ModuleName=script", definition)
                        script = archive.read(script_path).decode()
                        self.assertIn(f"{name}.script", definition)
                        self.assertIn("animation.phase += 0.48", script)
                        self.assertIn("animation.index >= 96", script)
                        self.assertIn("layout.frame_width = 640", script)
                        self.assertIn("Plymouth.SetBootProgressFunction", script)
                        png = archive.read(frame_entries[0])
                        self.assertEqual(b"\x89PNG\r\n\x1a\n", png[:8])
                        self.assertEqual(
                            (640, 360), struct.unpack(">II", png[16:24])
                        )
                    else:
                        progress_entries = sorted(
                            entry
                            for entry in entries
                            if f"{name}/resources/progress-" in entry
                        )
                        self.assertEqual(51, len(progress_entries))
                        self.assertIn("ModuleName=two-step", definition)

    def test_colour_switcher_lists_all_variants(self):
        result = subprocess.run(
            [str(THEMES / "blackarch" / "install.sh"), "--list"],
            cwd=REPOSITORY,
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertEqual(
            [f"{colour}-{variant}" for colour, variant in THEME_VARIANTS],
            result.stdout.splitlines(),
        )


if __name__ == "__main__":
    unittest.main()
