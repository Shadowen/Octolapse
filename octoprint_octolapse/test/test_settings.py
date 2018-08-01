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
from tempfile import NamedTemporaryFile

from google.protobuf.json_format import MessageToJson, Parse

from octoprint_octolapse.bin.python.point3d_pb2 import Point3D
from octoprint_octolapse.bin.python.printer_settings_pb2 import PrinterSettings
from octoprint_octolapse.settings import OctolapseSettings


class TestSettings(unittest.TestCase):
    def setUp(self):
        self.octolapse_settings = OctolapseSettings(NamedTemporaryFile().name)

    def tearDown(self):
        pass

    def test_createPrinterSettings(self):
        s = PrinterSettings()
        self.assertEqual(s.name, "New Printer")

    def test_editPrinterSettings(self):
        s = PrinterSettings()
        s.origin.x = 0
        s.origin.y = 1
        s.origin.z = 2

        self.assertEqual(s.origin.x, 0)
        self.assertEqual(s.origin.y, 1)
        self.assertEqual(s.origin.z, 2)

    def test_copyPrinterSettings(self):
        s = PrinterSettings()
        s.name = "My name"
        s.description = "My description"

        t = PrinterSettings()
        t.CopyFrom(s)

        self.assertEqual(t.name, "My name")
        self.assertEqual(t.description, "My description")

    def test_copyPrinterOrigin(self):
        s = PrinterSettings()

        p = Point3D(x=0, y=1, z=2)
        s.origin.CopyFrom(p)

        self.assertEqual(s.origin.x, 0)
        self.assertEqual(s.origin.y, 1)
        self.assertEqual(s.origin.z, 2)

    def test_printerSettingsToJson(self):
        s = PrinterSettings()
        jsonObj = MessageToJson(s, including_default_value_fields=True)

        # Attempt to parse the json object back in.
        parsed = json.loads(jsonObj)
        # Make sure some random fields are still there.
        self.assertIn('name', parsed)
        self.assertIn('description', parsed)
        self.assertIn('snapshotCommand', parsed)
        # Check the field values.
        self.assertDictContainsSubset({'snapshotCommand': 'snap',
                                       'autoPositionDetectionCommands': [],
                                       'autoDetectPosition': True}, parsed)

    def test_printerSettingsFromJson(self):
        s = PrinterSettings()
        Parse(
            """{\n  "snapshotCommand": "snap", \n  "autoPositionDetectionCommands": [], \n  "autoDetectPosition": true, \n  "name": "New Printer", \n  "defaultFirmwareRetractionsZhop": false, \n  "xyzAxesDefaultMode": "REQUIRE_EXPLICIT", \n  "unitsDefault": "millimeters", \n  "axisSpeedDisplayUnits": "MM_MIN", \n  "eAxisDefaultMode": "REQUIRE_EXPLICIT", \n  "defaultFirmwareRetractions": false, \n  "overrideOctoprintPrintVolume": false, \n  "abortOutOfBounds": true, \n  "guid": 0, \n  "g90InfluencesExtruder": "USE_OCTOPRINT", \n  "printerPositionConfirmationTolerance": 0.0010000000474974513, \n  "primingHeight": 0.75, \n  "description": ""\n}"""
            , s)

        self.assertEqual(s.name, 'New Printer')
        # Watch out! The Protobuf compiler converts between snake and camel case depending on the language.
        self.assertEqual(s.snapshot_command, 'snap')
