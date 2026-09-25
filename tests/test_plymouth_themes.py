import struct
import subprocess
import unittest
from pathlib import Path
from zipfile import ZipFile


REPOSITORY = Path(__file__).resolve().parents[1]
THEMES = REPOSITORY / "themes"
COLOURS = ("green", "orange", "purple", "red")


class BlackArchPlymouthPackageTests(unittest.TestCase):
    def test_each_archive_is_a_complete_script_theme(self):
        for colour in COLOURS:
            with self.subTest(colour=colour):
                name = f"blackarch-{colour}"
                archive_path = THEMES / name / "plymouth" / f"{name}.zip"
                self.assertTrue(archive_path.is_file())

                with ZipFile(archive_path) as archive:
                    entries = set(archive.namelist())
                    definition_path = f"{name}/{name}.plymouth"
                    script_path = f"{name}/{name}.script"
                    self.assertIn(definition_path, entries)
                    self.assertIn(script_path, entries)
                    self.assertIn(f"{name}/dialog/entry.png", entries)
                    self.assertIn(f"{name}/dialog/lock.png", entries)
                    self.assertIn(f"{name}/dialog/bullet.png", entries)

                    frame_entries = sorted(
                        entry for entry in entries if f"{name}/frames/frame-" in entry
                    )
                    progress_entries = sorted(
                        entry for entry in entries if f"{name}/progress/progress-" in entry
                    )
                    self.assertEqual(24, len(frame_entries))
                    self.assertEqual(51, len(progress_entries))

                    definition = archive.read(definition_path).decode()
                    script = archive.read(script_path).decode()
                    self.assertIn("ModuleName=script", definition)
                    self.assertIn(f"themes/{name}", definition)
                    self.assertIn(f"{name}.script", definition)
                    self.assertIn("animation.phase += 0.36", script)
                    self.assertIn("Plymouth.SetBootProgressFunction", script)

                    png = archive.read(frame_entries[0])
                    self.assertEqual(b"\x89PNG\r\n\x1a\n", png[:8])
                    self.assertEqual((720, 720), struct.unpack(">II", png[16:24]))

    def test_colour_switcher_lists_all_variants(self):
        result = subprocess.run(
            [str(THEMES / "blackarch" / "install.sh"), "--list"],
            cwd=REPOSITORY,
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertEqual([*COLOURS], result.stdout.splitlines())


if __name__ == "__main__":
    unittest.main()
