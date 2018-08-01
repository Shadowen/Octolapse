# coding=utf-8
##################################################################################
# Octolapse - A plugin for OctoPrint used for making stabilized timelapse videos.
# Copyright (C) 2017  Brad Hochgesang
##################################################################################
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see the following:
# https://github.com/FormerLurker/Octolapse/blob/master/LICENSE
#
# You can contact the author either through the git-hub repository, or at the
# following email address: FormerLurker@pm.me
##################################################################################
import json
import unittest

from octoprint_octolapse.settings import Settings, RenderingSettings, InvalidSettingsKeyException


class TestSettings(unittest.TestCase):
    def test_renderingSettingsDefaults(self):
        # Default initialize a RenderingSettings object.
        rendering = RenderingSettings()
        # Check some values are set to defaults.
        self.assertNotEqual(rendering.guid, None)
        self.assertEqual(rendering.name, "Default Rendering")
        self.assertEqual(rendering.fps_calculation_type, "duration")

    def test_renderingSettingsJSON(self):
        # Default initialize a RenderingSettings object.
        rendering = RenderingSettings()

        # Check conversion to json.
        json_str = rendering.to_json()
        self.assertEqual(str, type(json_str))
        # Check that the JSON is valid.
        json.loads(json_str)

        # ...and convert back from json.
        parsed = RenderingSettings.from_json(json_str)
        self.assertDictEqual(vars(rendering), vars(parsed))

        # We can even automatically detect the type from the JSON!
        parsed_autodetect = Settings.from_json(json_str)
        self.assertEqual(RenderingSettings, parsed_autodetect.__class__)
        self.assertDictEqual(vars(rendering), vars(parsed_autodetect))

    def test_copyRenderingSettings(self):
        # Here is a rendering settings object.
        rendering = RenderingSettings()
        rendering.name = 'A custom name'
        rendering.description = 'A custom description'
        rendering.fps = 1.15
        rendering.overlay_text_color = [1, 2, 3]

        # Copy it. Note you can also call `deepcopy(rendering)`, using the `copy` module.
        copy = rendering.__deepcopy__()
        # Ensure we actually did a deep copy.
        self.assertNotEqual(id(rendering), id(copy))
        self.assertNotEqual(id(rendering.overlay_text_color), id(copy.overlay_text_color))

        # Make sure the copy is identical.
        self.assertEqual(rendering.name, copy.name)
        self.assertEqual(rendering.description, copy.description)
        self.assertEqual(rendering.fps, copy.fps)
        self.assertEqual(rendering.overlay_text_color, copy.overlay_text_color)

    def test_updateRenderingSettingsFromDict(self):
        rendering = RenderingSettings()

        # Attempt some updates.
        rendering.update({'fps': 1.2, 'overlay_text_template': "foo bar baz"})

        # Make sure our updates made it.
        self.assertEqual(rendering.fps, 1.2)
        self.assertEqual(rendering.overlay_text_template, "foo bar baz")

    def test_addKeyToRenderingSettings(self):
        rendering = RenderingSettings()

        # If we try to add any keys that shouldn't be in the Settings object, it'll reject them automatically with an
        # exception.
        self.assertRaises(InvalidSettingsKeyException, lambda: rendering.update({'keyDoesntExist': 'value'}))
