"""Backend selection uses one configuration and one shared card/editor surface."""
import importlib.util
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('poedash_backends',ROOT/'apps/poedash/poedash.py')
app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)

class BackendSelection(unittest.TestCase):
    def test_default_selection_environment_override_and_invalid_mode(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'POEDASH_BACKEND':''}):
            root=Path(tmp)
            self.assertEqual(app.surface_backend(root),'gtk')
            (root/'surface-backend').write_text('eww\n')
            self.assertEqual(app.surface_backend(root),'eww')
            with patch.dict(os.environ,{'POEDASH_BACKEND':'gtk'}):self.assertEqual(app.surface_backend(root),'gtk')
            (root/'surface-backend').write_text('unsupported')
            with self.assertRaises(ValueError):app.surface_backend(root)

    def test_eww_selection_renders_shared_host_instead_of_legacy_pollers(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'POEDASH_BACKEND':''}),patch.object(app,'monitor_info',return_value=None):
            root=Path(tmp)
            shutil.copytree(ROOT/'apps/poedash/assets/templates',root/'templates')
            (root/'scripts').mkdir()
            shutil.copy2(ROOT/'apps/poedash/assets/scripts/config.py',root/'scripts/config.py')
            shutil.copy2(ROOT/'apps/poedash/assets/settings.example.json',root/'settings.json')
            (root/'surface-backend').write_text('eww')
            app.render(root)
            text=(root/'eww.yuck').read_text()
            self.assertIn('poedash-shared-host',text)
            self.assertNotIn('defpoll',text)
            self.assertNotIn('refresh.py',text)
            self.assertIn(':stacking "bottom"',text)
