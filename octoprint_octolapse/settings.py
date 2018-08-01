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

import copy
import json
import logging
import math
import uuid
from datetime import datetime

import concurrent

import octoprint_octolapse.utility as utility

PROFILE_SNAPSHOT_GCODE_TYPE = "gcode"


class Settings(object):
    # Secret key used to encode the class of the current object in JSON.
    # Nobody checks, but don't use this key in any Settings object.
    class_key = '_class'

    def __init__(self, name, guid=None, **kwargs):
        # All instance variables must be JSON-encodable. If not, extend JSONEncoder in the subclass.
        self.guid = guid if guid is not None else str(uuid.uuid4())
        self.name = name

        self.update(kwargs)

    def update(self, changes):
        """
        Updates the Settings object to match the changes object.
        :param changes: An object of the same Settings class to copy from.
                        Can also be a dictionary reflecting the part of the schema of the Settings object.
        Deep-copies all values in `changes` to avoid pass-by-reference issues.
        """
        if issubclass(changes.__class__, self.__class__):
            # Update using an identical settings class.
            return vars(self).update({k: copy.deepcopy(v) for k, v in vars(changes).items()})
        elif hasattr(changes, 'items'):
            # Verify all changes have valid keys.
            for k, v in changes.items():
                if k not in vars(self).keys():
                    raise InvalidSettingsKeyException(self.__class__, k, v)
            # Do a normal dict update.
            return vars(self).update({k: copy.deepcopy(v) for k, v in changes.items()})
        # We don't know how to read data from this type.
        raise InvalidSettingsException(self.__class__,
                                       "Cannot use {} to update {}.".format(changes.__class__, self.__class__))

    class JSONEncoder(json.JSONEncoder):
        """Handles encoding Settings objects as strings."""

        def default(self, obj):
            if isinstance(obj, dict):
                return obj
            elif issubclass(obj.__class__, Settings):
                d = {k: v for k, v in vars(obj).items()}
                d.update({Settings.class_key: obj.__class__.__name__})
                # Recursive call to make sure everything works fine.
                return self.default(d)

            # Let the base class default method raise the TypeError
            return json.JSONEncoder.default(self, obj)

    def to_json(self):
        """Dumps the Settings object to a JSON-formatted string."""
        return json.dumps(self, cls=self.JSONEncoder)

    class JSONDecoder(json.JSONDecoder):
        """Handles decoding Settings objects from JSON."""

        def __init__(self, *args, **kwargs):
            json.JSONDecoder.__init__(self, object_hook=self.object_hook, *args, **kwargs)

        @staticmethod
        def object_hook(obj):
            # Known classes.
            if Settings.class_key in obj:
                # Remove the class key since we don't need it anymore.
                class_name = obj.pop(Settings.class_key)
                # Retrieve the correct class.
                for subclass in Settings.__subclasses__():
                    if subclass.__name__ == class_name:
                        inst = subclass.__new__(subclass)
                        inst.__init__(**obj)
                        return inst

            # It's a normal JSON object; follow normal JSON->Python guidelines.
            return obj

    @classmethod
    def from_json(cls, s):
        """
        Loads the Settings object from a string. Can automatically detect and load Settings subclasses.
        :param s: a string containing a JSON-formatted Settings object.
        """
        inst = json.loads(s, cls=cls.JSONDecoder)
        return inst

    def __deepcopy__(self):
        """Deep copies a Settings object."""
        cp = self.__new__(self.__class__)
        cp.update(self)
        return cp


class InvalidSettingsException(Exception):
    def __init__(self, settings_class, message):
        Exception.__init__(self, message)
        self.settings_class = settings_class
        self.message = message


class InvalidSettingsKeyException(Exception):
    def __init__(self, settings_class, key, value=None):
        self.settings_class = settings_class
        self.key = key
        self.value = value
        Exception.__init__(self, self.__repr__())

    def __str__(self):
        return repr(self)

    def __repr__(self):
        return "Tried to set {} in {} to {}.".format(self.key, self.settings_class, self.value)


class PrinterSettings(Settings):
    def __init__(self, name="New Printer", **kwargs):
        self.description = ""
        self.retract_length = 2.0
        self.retract_speed = 6000
        self.detract_speed = 3000
        self.movement_speed = 6000
        self.z_hop = .5
        self.z_hop_speed = 6000
        self.retract_speed = 4000
        self.snapshot_command = "snap"
        self.printer_position_confirmation_tolerance = 0.001
        self.auto_detect_position = True
        self.origin_x = None
        self.origin_y = None
        self.origin_z = None
        self.abort_out_of_bounds = True
        self.override_octoprint_print_volume = False
        self.min_x = 0.0
        self.max_x = 0.0
        self.min_y = 0.0
        self.max_y = 0.0
        self.min_z = 0.0
        self.max_z = 0.0
        self.auto_position_detection_commands = ""
        self.priming_height = 0.75
        self.e_axis_default_mode = 'require-explicit'  # other values are 'relative' and 'absolute'
        self.g90_influences_extruder = 'use-octoprint-settings'  # other values are 'true' and 'false'
        self.xyz_axes_default_mode = 'require-explicit'  # other values are 'relative' and 'absolute'
        self.units_default = 'millimeters'
        self.axis_speed_display_units = 'mm-min'
        self.default_firmware_retractions = False
        self.default_firmware_retractions_zhop = False
        super(PrinterSettings, self).__init__(name, **kwargs)


class StabilizationPath(object):
    def __init__(self):
        self.Axis = ""
        self.Path = []
        self.CoordinateSystem = ""
        self.Index = 0
        self.Loop = True
        self.InvertLoop = True
        self.Increment = 1
        self.CurrentPosition = None
        self.Type = 'disabled'
        self.Options = {}


class StabilizationSettings(Settings):
    def __init__(self, name="Default Stabilization", **kwargs):
        self.description = ""
        self.x_type = "relative"
        self.x_fixed_coordinate = 0.0
        self.x_fixed_path = "0"
        self.x_fixed_path_loop = True
        self.x_fixed_path_invert_loop = True
        self.x_relative = 50.0
        self.x_relative_print = 50.0
        self.x_relative_path = "50.0"
        self.x_relative_path_loop = True
        self.x_relative_path_invert_loop = True
        self.y_type = 'relative'
        self.y_fixed_coordinate = 0.0
        self.y_fixed_path = "0"
        self.y_fixed_path_loop = True
        self.y_fixed_path_invert_loop = True
        self.y_relative = 50.0
        self.y_relative_print = 50.0
        self.y_relative_path = "50"
        self.y_relative_path_loop = True
        self.y_relative_path_invert_loop = True

        super(StabilizationSettings, self).__init__(name, **kwargs)

    def get_stabilization_paths(self):
        x_stabilization_path = StabilizationPath()
        x_stabilization_path.Axis = "X"
        x_stabilization_path.Type = self.x_type
        if self.x_type == 'fixed_coordinate':
            x_stabilization_path.Path.append(self.x_fixed_coordinate)
            x_stabilization_path.CoordinateSystem = 'absolute'
        elif self.x_type == 'relative':
            x_stabilization_path.Path.append(self.x_relative)
            x_stabilization_path.CoordinateSystem = 'bed_relative'
        elif self.x_type == 'fixed_path':
            x_stabilization_path.Path = self.parse_csv_path(self.x_fixed_path)
            x_stabilization_path.CoordinateSystem = 'absolute'
            x_stabilization_path.Loop = self.x_fixed_path_loop
            x_stabilization_path.InvertLoop = self.x_fixed_path_invert_loop
        elif self.x_type == 'relative_path':
            x_stabilization_path.Path = self.parse_csv_path(self.x_relative_path)
            x_stabilization_path.CoordinateSystem = 'bed_relative'
            x_stabilization_path.Loop = self.x_relative_path_loop
            x_stabilization_path.InvertLoop = self.x_relative_path_invert_loop

        y_stabilization_path = StabilizationPath()
        y_stabilization_path.Axis = "Y"
        y_stabilization_path.Type = self.y_type
        if self.y_type == 'fixed_coordinate':
            y_stabilization_path.Path.append(self.y_fixed_coordinate)
            y_stabilization_path.CoordinateSystem = 'absolute'
        elif self.y_type == 'relative':
            y_stabilization_path.Path.append(self.y_relative)
            y_stabilization_path.CoordinateSystem = 'bed_relative'
        elif self.y_type == 'fixed_path':
            y_stabilization_path.Path = self.parse_csv_path(self.y_fixed_path)
            y_stabilization_path.CoordinateSystem = 'absolute'
            y_stabilization_path.Loop = self.y_fixed_path_loop
            y_stabilization_path.InvertLoop = self.y_fixed_path_invert_loop
        elif self.y_type == 'relative_path':
            y_stabilization_path.Path = self.parse_csv_path(self.y_relative_path)
            y_stabilization_path.CoordinateSystem = 'bed_relative'
            y_stabilization_path.Loop = self.y_relative_path_loop
            y_stabilization_path.InvertLoop = self.y_relative_path_invert_loop

        return dict(
            X=x_stabilization_path,
            Y=y_stabilization_path
        )

    @staticmethod
    def parse_csv_path(path_csv):
        """Converts a list of floats separated by commas into an array of floats."""
        path = []
        items = path_csv.split(',')
        for item in items:
            item = item.strip()
            if len(item) > 0:
                path.append(float(item))
        return path


class SnapshotPositionRestrictions(object):
    def __init__(self, restriction_type, shape, x, y, x2=None, y2=None, r=None, calculate_intersections=False):

        self.Type = restriction_type.lower()
        if self.Type not in ["forbidden", "required"]:
            raise TypeError("SnapshotPosition type must be 'forbidden' or 'required'")

        self.Shape = shape.lower()

        if self.Shape not in ["rect", "circle"]:
            raise TypeError("SnapshotPosition shape must be 'rect' or 'circle'")
        if x is None or y is None:
            raise TypeError(
                "SnapshotPosition requires that x and y are not None")
        if self.Shape == 'rect' and (x2 is None or y2 is None):
            raise TypeError(
                "SnapshotPosition shape=rect requires that x2 and y2 are not None")
        if self.Shape == 'circle' and r is None:
            raise TypeError(
                "SnapshotPosition shape=circle requires that r is not None")

        self.Type = restriction_type
        self.Shape = shape
        self.X = float(x)
        self.Y = float(y)
        self.X2 = float(x2)
        self.Y2 = float(y2)
        self.R = float(r)
        self.CalculateIntersections = calculate_intersections

    def to_dict(self):
        return {
            'Type': self.Type,
            'Shape': self.Shape,
            'X': self.X,
            'Y': self.Y,
            'X2': self.X2,
            'Y2': self.Y2,
            'R': self.R,
            'CalculateIntersections': self.CalculateIntersections
        }

    def get_intersections(self, x, y, previous_x, previous_y):
        if not self.CalculateIntersections:
            return False

        if x is None or y is None or previous_x is None or previous_y is None:
            return False

        if self.Shape == 'rect':
            intersections = utility.get_intersections_rectangle(previous_x, previous_y, x, y, self.X, self.Y, self.X2,
                                                                self.Y2)
        elif self.Shape == 'circle':
            intersections = utility.get_intersections_circle(previous_x, previous_y, x, y, self.X, self.Y, self.R)
        else:
            raise TypeError("SnapshotPosition shape must be 'rect' or 'circle'.")

        if not intersections:
            return False

        return intersections

    def is_in_position(self, x, y, tolerance):
        if x is None or y is None:
            return False

        if self.Shape == 'rect':
            return self.X <= x <= self.X2 and self.Y <= y <= self.Y2
        elif self.Shape == 'circle':
            lsq = math.pow(x - self.X, 2) + math.pow(y - self.Y, 2)
            rsq = math.pow(self.R, 2)
            return utility.is_close(lsq, rsq, tolerance) or lsq < rsq
        else:
            raise TypeError("SnapshotPosition shape must be 'rect' or 'circle'.")


class SnapshotSettings(Settings):
    # globals
    # Extruder Trigger Options
    ExtruderTriggerIgnoreValue = ""
    ExtruderTriggerRequiredValue = "trigger_on"
    ExtruderTriggerForbiddenValue = "forbidden"
    ExtruderTriggerOptions = [
        dict(value=ExtruderTriggerIgnoreValue, name='Ignore', visible=True),
        dict(value=ExtruderTriggerRequiredValue, name='Trigger', visible=True),
        dict(value=ExtruderTriggerForbiddenValue, name='Forbidden', visible=True)
    ]

    def __init__(self, name="Default Snapshot", **kwargs):
        self.description = ""
        # Initialize defaults
        # Gcode Trigger
        self.gcode_trigger_enabled = False
        self.gcode_trigger_require_zhop = False
        self.gcode_trigger_on_extruding_start = None
        self.gcode_trigger_on_extruding = None
        self.gcode_trigger_on_primed = None
        self.gcode_trigger_on_retracting_start = None
        self.gcode_trigger_on_retracting = None
        self.gcode_trigger_on_partially_retracted = None
        self.gcode_trigger_on_retracted = None
        self.gcode_trigger_on_detracting_start = None
        self.gcode_trigger_on_detracting = None
        self.gcode_trigger_on_detracted = None
        # Timer Trigger
        self.timer_trigger_enabled = False
        self.timer_trigger_seconds = 30
        self.timer_trigger_require_zhop = False
        self.timer_trigger_on_extruding_start = True
        self.timer_trigger_on_extruding = False
        self.timer_trigger_on_primed = True
        self.timer_trigger_on_retracting_start = False
        self.timer_trigger_on_retracting = False
        self.timer_trigger_on_partially_retracted = False
        self.timer_trigger_on_retracted = True
        self.timer_trigger_on_detracting_start = True
        self.timer_trigger_on_detracting = False
        self.timer_trigger_on_detracted = False
        # Layer Trigger
        self.layer_trigger_enabled = True
        self.layer_trigger_height = 0.0
        self.layer_trigger_require_zhop = False
        self.layer_trigger_on_extruding_start = True
        self.layer_trigger_on_extruding = None
        self.layer_trigger_on_primed = True
        self.layer_trigger_on_retracting_start = False
        self.layer_trigger_on_retracting = False
        self.layer_trigger_on_partially_retracted = False
        self.layer_trigger_on_retracted = True
        self.layer_trigger_on_detracting_start = True
        self.layer_trigger_on_detracting = False
        self.layer_trigger_on_detracted = False
        # other settings
        self.position_restrictions = []
        self.lift_before_move = True
        self.retract_before_move = True

        self.cleanup_after_render_complete = True
        self.cleanup_after_render_fail = False

        super(SnapshotSettings, self).__init__(name, **kwargs)

    def get_extruder_trigger_value_string(self, value):
        if value is None:
            return self.ExtruderTriggerIgnoreValue
        elif value:
            return self.ExtruderTriggerRequiredValue
        elif not value:
            return self.ExtruderTriggerForbiddenValue

    def get_extruder_trigger_value(self, value):
        if isinstance(value, basestring):
            if value is None:
                return None
            elif value.lower() == self.ExtruderTriggerRequiredValue:
                return True
            elif value.lower() == self.ExtruderTriggerForbiddenValue:
                return False
            else:
                return None
        else:
            return bool(value)

    @staticmethod
    def get_trigger_position_restrictions(value):
        restrictions = []
        for restriction in value:
            restrictions.append(
                SnapshotPositionRestrictions(
                    restriction["Type"], restriction["Shape"],
                    restriction["X"], restriction["Y"],
                    restriction["X2"], restriction["Y2"],
                    restriction["R"], restriction["CalculateIntersections"]
                )
            )
        return restrictions

    @staticmethod
    def get_trigger_position_restrictions_value_string(values):
        restrictions = []
        for restriction in values:
            restrictions.append(restriction.to_dict())
        return restrictions


class RenderingSettings(Settings):
    def __init__(self, guid=None, name="Default Rendering", **kwargs):
        self.description = ""
        self.enabled = True
        self.fps_calculation_type = 'duration'
        self.run_length_seconds = 5
        self.fps = 30
        self.max_fps = 120.0
        self.min_fps = 2.0
        self.output_format = 'mp4'
        self.sync_with_timelapse = True
        self.bitrate = "8000K"
        self.post_roll_seconds = 0
        self.pre_roll_seconds = 0
        self.output_template = "{FAILEDFLAG}{FAILEDSEPARATOR}{GCODEFILENAME}_{PRINTENDTIME}"
        self.enable_watermark = False
        self.selected_watermark = ""
        self.overlay_text_template = ""
        self.overlay_font_path = ""
        self.overlay_font_size = 10
        self.overlay_text_pos = [10, 10]
        self.overlay_text_color = [255, 255, 255, 128]

        super(RenderingSettings, self).__init__(guid=guid, name=name, **kwargs)


class CameraSettings(Settings):

    def __init__(self, guid=None, name="Default Camera", **kwargs):
        self.description = ""
        self.camera_type = "webcam"
        self.external_camera_snapshot_script = ""
        self.delay = 125
        self.apply_settings_before_print = False
        self.address = "http://127.0.0.1/webcam/"
        self.snapshot_request_template = "{camera_address}?action=snapshot"
        self.snapshot_transpose = ""
        self.ignore_ssl_error = False
        self.username = ""
        self.password = ""
        self.brightness = 128
        self.brightness_request_template = self.template_to_string(0, 0, 9963776, 1)
        self.contrast = 128
        self.contrast_request_template = self.template_to_string(0, 0, 9963777, 1)
        self.saturation = 128
        self.saturation_request_template = self.template_to_string(0, 0, 9963778, 1)
        self.white_balance_auto = True
        self.white_balance_auto_request_template = self.template_to_string(0, 0, 9963788, 1)
        self.gain = 100
        self.gain_request_template = self.template_to_string(0, 0, 9963795, 1)
        self.powerline_frequency = 60
        self.powerline_frequency_request_template = self.template_to_string(0, 0, 9963800, 1)
        self.white_balance_temperature = 4000
        self.white_balance_temperature_request_template = self.template_to_string(0, 0, 9963802, 1)
        self.sharpness = 128
        self.sharpness_request_template = self.template_to_string(0, 0, 9963803, 1)
        self.backlight_compensation_enabled = False
        self.backlight_compensation_enabled_request_template = self.template_to_string(0, 0, 9963804, 1)
        self.exposure_type = 1
        self.exposure_type_request_template = self.template_to_string(0, 0, 10094849, 1)
        self.exposure = 250
        self.exposure_request_template = self.template_to_string(0, 0, 10094850, 1)
        self.exposure_auto_priority_enabled = True
        self.exposure_auto_priority_enabled_request_template = self.template_to_string(0, 0, 10094851, 1)
        self.pan = 0
        self.pan_request_template = self.template_to_string(0, 0, 10094856, 1)
        self.tilt = 0
        self.tilt_request_template = self.template_to_string(0, 0, 10094857, 1)
        self.autofocus_enabled = True
        self.autofocus_enabled_request_template = self.template_to_string(0, 0, 10094860, 1)
        self.focus = 28
        self.focus_request_template = self.template_to_string(0, 0, 10094858, 1)
        self.zoom = 100
        self.zoom_request_template = self.template_to_string(0, 0, 10094861, 1)
        self.led1_mode = 'auto'
        self.led1_mode_request_template = self.template_to_string(0, 0, 168062213, 1)
        self.led1_frequency = 0
        self.led1_frequency_request_template = self.template_to_string(0, 0, 168062214, 1)
        self.jpeg_quality = 90
        self.jpeg_quality_request_template = self.template_to_string(0, 0, 1, 3)

        super(CameraSettings, self).__init__(guid=guid, name=name, **kwargs)

    @staticmethod
    def template_to_string(destination, plugin, setting_id, group):
        return (
            "{camera_address}?action=command&"
            + "dest=" + str(destination)
            + "&plugin=" + str(plugin)
            + "&id=" + str(setting_id)
            + "&group=" + str(group)
            + "&value={value}"
        )


class DebugProfile(Settings):
    Logger = None
    FormatString = '%(asctime)s - %(levelname)s - %(message)s'
    ConsoleFormatString = '{asctime} - {levelname} - {message}'
    Logging_Executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def get_logger(self):
        _logger = logging.getLogger(
            "octoprint.plugins.octolapse")

        from octoprint.logging.handlers import CleaningTimedRotatingFileHandler
        octoprint_logging_handler = CleaningTimedRotatingFileHandler(
            self.logFilePath, when="D", backupCount=3)

        octoprint_logging_handler.setFormatter(
            logging.Formatter("%(asctime)s %(message)s"))
        octoprint_logging_handler.setLevel(logging.DEBUG)
        _logger.addHandler(octoprint_logging_handler)
        _logger.propagate = False
        # we are controlling our logging via settings, so set to debug so that nothing is filtered
        _logger.setLevel(logging.DEBUG)

        return _logger

    def __init__(self, log_file_path, guid=None, name="Default Debug Profile", **kwargs):
        self.logFilePath = log_file_path
        self.description = ""
        # Configure the logger if it has not been created
        if DebugProfile.Logger is None:
            DebugProfile.Logger = self.get_logger()

        self.log_to_console = False
        self.enabled = False
        self.is_test_mode = False
        self.position_change = False
        self.position_command_received = False
        self.extruder_change = False
        self.extruder_triggered = False
        self.trigger_create = False
        self.trigger_wait_state = False
        self.trigger_triggering = False
        self.trigger_triggering_state = False
        self.trigger_layer_change = False
        self.trigger_height_change = False
        self.trigger_zhop = False
        self.trigger_time_unpaused = False
        self.trigger_time_remaining = False
        self.snapshot_gcode = False
        self.snapshot_gcode_endcommand = False
        self.snapshot_position = False
        self.snapshot_position_return = False
        self.snapshot_position_resume_print = False
        self.snapshot_save = False
        self.snapshot_download = False
        self.render_start = False
        self.render_complete = False
        self.render_fail = False
        self.render_sync = False
        self.snapshot_clean = False
        self.settings_save = False
        self.settings_load = False
        self.print_state_changed = False
        self.camera_settings_apply = False
        self.gcode_sent_all = False
        self.gcode_queuing_all = False
        self.gcode_received_all = False

        super(DebugProfile, self).__init__(guid=guid, name=name, **kwargs)

    def log_console(self, level_name, message, force=False):
        if self.log_to_console or force:
            print(DebugProfile.ConsoleFormatString.format(asctime=str(
                datetime.now()), levelname=level_name, message=message))

    def log_info(self, message):
        if self.enabled:
            DebugProfile.Logging_Executor.submit(self.Logger.info, message)
            self.log_console('info', message)

    def log_warning(self, message):
        if self.enabled:
            DebugProfile.Logging_Executor.submit(self.Logger.warning, message)
            self.log_console('warn', message)

    def log_exception(self, exception):
        message = utility.exception_to_string(exception)
        DebugProfile.Logging_Executor.submit(self.Logger.error, message)
        self.log_console('error', message)

    def log_error(self, message):
        DebugProfile.Logging_Executor.submit(self.Logger.error, message)
        self.log_console('error', message)

    def log_position_change(self, message):
        if self.position_change:
            self.log_info(message)

    def log_position_command_received(self, message):
        if self.position_command_received:
            self.log_info(message)

    def log_extruder_change(self, message):
        if self.extruder_change:
            self.log_info(message)

    def log_extruder_triggered(self, message):
        if self.extruder_triggered:
            self.log_info(message)

    def log_trigger_create(self, message):
        if self.trigger_create:
            self.log_info(message)

    def log_trigger_wait_state(self, message):
        if self.trigger_wait_state:
            self.log_info(message)

    def log_triggering(self, message):
        if self.trigger_triggering:
            self.log_info(message)

    def log_triggering_state(self, message):
        if self.trigger_triggering_state:
            self.log_info(message)

    def log_trigger_height_change(self, message):
        if self.trigger_height_change:
            self.log_info(message)

    def log_position_layer_change(self, message):
        if self.position_change:
            self.log_info(message)

    def log_position_height_change(self, message):
        if self.position_change:
            self.log_info(message)

    def log_position_zhop(self, message):
        if self.trigger_zhop:
            self.log_info(message)

    def log_timer_trigger_unpaused(self, message):
        if self.trigger_time_unpaused:
            self.log_info(message)

    def log_trigger_time_remaining(self, message):
        if self.trigger_time_remaining:
            self.log_info(message)

    def log_snapshot_gcode(self, message):
        if self.snapshot_gcode:
            self.log_info(message)

    def log_snapshot_gcode_end_command(self, message):
        if self.snapshot_gcode_endcommand:
            self.log_info(message)

    def log_snapshot_position(self, message):
        if self.snapshot_position:
            self.log_info(message)

    def log_snapshot_return_position(self, message):
        if self.snapshot_position_return:
            self.log_info(message)

    def log_snapshot_resume_position(self, message):
        if self.snapshot_position_resume_print:
            self.log_info(message)

    def log_snapshot_save(self, message):
        if self.snapshot_save:
            self.log_info(message)

    def log_snapshot_download(self, message):
        if self.snapshot_download:
            self.log_info(message)

    def log_render_start(self, message):
        if self.render_start:
            self.log_info(message)

    def log_render_complete(self, message):
        if self.render_complete:
            self.log_info(message)

    def log_render_fail(self, message):
        if self.render_fail:
            self.log_info(message)

    def log_render_sync(self, message):
        if self.render_sync:
            self.log_info(message)

    def log_snapshot_clean(self, message):
        if self.snapshot_clean:
            self.log_info(message)

    def log_settings_save(self, message):
        if self.settings_save:
            self.log_info(message)

    def log_settings_load(self, message):
        if self.settings_load:
            self.log_info(message)

    def log_print_state_change(self, message):
        if self.print_state_changed:
            self.log_info(message)

    def log_camera_settings_apply(self, message):
        if self.camera_settings_apply:
            self.log_info(message)

    def log_gcode_sent(self, message):
        if self.gcode_sent_all:
            self.log_info(message)

    def log_gcode_queuing(self, message):
        if self.gcode_queuing_all:
            self.log_info(message)

    def log_gcode_received(self, message):
        if self.gcode_received_all:
            self.log_info(message)


class OctolapseSettings(Settings):
    DefaultDebugProfile = None
    Logger = None

    # constants

    def __init__(self, log_file_path, plugin_version="unknown", **kwargs):
        self.rendering_file_templates = [
            "FAILEDFLAG",
            "FAILEDSTATE",
            "FAILEDSEPARATOR",
            "PRINTSTATE",
            "GCODEFILENAME",
            "DATETIMESTAMP",
            "PRINTENDTIME",
            "PRINTENDTIMESTAMP",
            "PRINTSTARTTIME",
            "PRINTSTARTTIMESTAMP",
            "SNAPSHOTCOUNT",
            "FPS"
        ]
        self.overlay_text_templates = [
            "snapshot_number",
            "current_time",
            "time_elapsed",
        ]
        self.DefaultPrinter = PrinterSettings(
            name="Default Printer", guid="5d39248f-5e11-4c42-b7f4-810c7acc287e")
        self.DefaultStabilization = StabilizationSettings(
            name="Default Stabilization", guid="3a94e945-f5d5-4655-909a-e61c1122cc1f")
        self.DefaultSnapshot = SnapshotSettings(
            name="Default Snapshot", guid="5d16f0cb-512c-476a-b32d-a10191ad0d0e")
        self.DefaultRendering = RenderingSettings(
            name="Default Rendering", guid="32d6ad28-0314-4a14-974c-0d7d92325f17")
        self.DefaultCamera = CameraSettings(
            name="Default Camera", guid="6b3361a7-82b7-4abf-b3d1-e3046d457d8c")
        self.DefaultDebugProfile = DebugProfile(
            log_file_path=log_file_path, name="Default Debug", guid="08ad284a-76cc-4854-b8a0-f2658b784dd7")
        self.LogFilePath = log_file_path

        self.version = plugin_version
        self.show_navbar_icon = True
        self.show_navbar_when_not_printing = True
        self.is_octolapse_enabled = True
        self.auto_reload_latest_snapshot = True
        self.auto_reload_frames = 5
        self.show_position_state_changes = False
        self.show_position_changes = False
        self.show_extruder_state_changes = False
        self.show_trigger_state_changes = False
        self.current_printer_profile_guid = None
        self.show_real_snapshot_time = False
        self.printers = {}

        stabilization = self.DefaultStabilization
        self.current_stabilization_profile_guid = stabilization.guid
        self.stabilizations = {stabilization.guid: stabilization}

        snapshot = self.DefaultSnapshot
        self.current_snapshot_profile_guid = snapshot.guid
        self.snapshots = {snapshot.guid: snapshot}

        rendering = self.DefaultRendering
        self.current_rendering_profile_guid = rendering.guid
        self.renderings = {rendering.guid: rendering}

        camera = self.DefaultCamera
        self.current_camera_profile_guid = camera.guid
        self.cameras = {camera.guid: camera}

        debug_profile = self.DefaultDebugProfile
        self.current_debug_profile_guid = debug_profile.guid
        self.debug_profiles = {debug_profile.guid: debug_profile}

        super(OctolapseSettings, self).__init__(name="Octolapse Settings", **kwargs)

    def current_stabilization(self):
        if len(self.stabilizations.keys()) == 0:
            stabilization = StabilizationSettings()
            self.stabilizations[stabilization.guid] = stabilization
            self.current_stabilization_profile_guid = stabilization.guid
        return self.stabilizations[self.current_stabilization_profile_guid]

    def current_snapshot(self):
        if len(self.snapshots.keys()) == 0:
            snapshot = SnapshotSettings()
            self.snapshots[snapshot.guid] = snapshot
            self.current_snapshot_profile_guid = snapshot.guid
        return self.snapshots[self.current_snapshot_profile_guid]

    def current_rendering(self):
        if len(self.renderings.keys()) == 0:
            rendering = RenderingSettings()
            self.renderings[rendering.guid] = rendering
            self.current_rendering_profile_guid = rendering.guid
        return self.renderings[self.current_rendering_profile_guid]

    def current_printer(self):
        if self.current_printer_profile_guid is None or self.current_printer_profile_guid not in self.printers:
            return None
        return self.printers[self.current_printer_profile_guid]

    def current_camera(self):
        if len(self.cameras.keys()) == 0:
            camera = CameraSettings()
            self.cameras[camera.guid] = camera
            self.current_camera_profile_guid = camera.guid
        return self.cameras[self.current_camera_profile_guid]

    def current_debug_profile(self):
        if len(self.debug_profiles.keys()) == 0:
            debug_profile = DebugProfile(self.LogFilePath)
            self.debug_profiles[debug_profile.guid] = debug_profile
            self.current_debug_profile_guid = debug_profile.guid
        return self.debug_profiles[self.current_debug_profile_guid]

    def get_current_profiles_description(self):
        return {
            "printer":
                "None Selected" if self.current_printer() is None
                else self.current_printer().name,
            "stabilization": "None Selected"
            if self.current_stabilization() is None
            else self.current_stabilization().name,
            "snapshot": "None Selected"
            if self.current_snapshot() is None
            else self.current_snapshot().name,
            "rendering": "None Selected"
            if self.current_rendering() is None
            else self.current_rendering().name,
            "camera": "None Selected"
            if self.current_camera() is None
            else self.current_camera().name,
            "debug_profile": "None Selected"
            if self.current_debug_profile() is None
            else self.current_debug_profile().name,
        }

    def get_profiles_dict(self):
        profiles_dict = {
            'current_printer_profile_guid': self.current_printer_profile_guid,
            'current_stabilization_profile_guid': self.current_stabilization_profile_guid,
            'current_snapshot_profile_guid': self.current_snapshot_profile_guid,
            'current_rendering_profile_guid': self.current_rendering_profile_guid,
            'current_camera_profile_guid': self.current_camera_profile_guid,
            'current_debug_profile_guid': self.current_debug_profile_guid,
            'printers': [],
            'stabilizations': [],
            'snapshots': [],
            'renderings': [],
            'cameras': [],
            'debug_profiles': []
        }

        for key, printer in self.printers.items():
            profiles_dict["printers"].append({
                "name": printer.name,
                "guid": printer.guid
            })

        for key, stabilization in self.stabilizations.items():
            profiles_dict["stabilizations"].append({
                "name": stabilization.name,
                "guid": stabilization.guid
            })

        for key, snapshot in self.snapshots.items():
            profiles_dict["snapshots"].append({
                "name": snapshot.name,
                "guid": snapshot.guid
            })

        for key, rendering in self.renderings.items():
            profiles_dict["renderings"].append({
                "name": rendering.name,
                "guid": rendering.guid
            })

        for key, camera in self.cameras.items():
            profiles_dict["cameras"].append({
                "name": camera.name,
                "guid": camera.guid
            })

        for key, debugProfile in self.debug_profiles.items():
            profiles_dict["debug_profiles"].append({
                "name": debugProfile.name,
                "guid": debugProfile.guid
            })
        return profiles_dict

    def get_main_settings_dict(self):
        return {
            'is_octolapse_enabled': self.is_octolapse_enabled,
            'version': self.version,
            'auto_reload_latest_snapshot': self.auto_reload_latest_snapshot,
            'auto_reload_frames': int(self.auto_reload_frames),
            'show_navbar_icon': self.show_navbar_icon,
            'show_navbar_when_not_printing': self.show_navbar_when_not_printing,
            'show_position_state_changes': self.show_position_state_changes,
            'show_position_changes': self.show_position_changes,
            'show_extruder_state_changes': self.show_extruder_state_changes,
            'show_trigger_state_changes': self.show_trigger_state_changes,
            'show_real_snapshot_time': self.show_real_snapshot_time
        }

    # Add/Update/Remove/set current profile

    def add_update_profile(self, profile_type, profile):
        # check the guid.  If it is null or empty, assign a new value.
        guid = profile["guid"]
        if guid is None or guid == "":
            guid = str(uuid.uuid4())
            profile["guid"] = guid

        if profile_type == "Printer":
            new_profile = PrinterSettings(profile)
            self.printers[guid] = new_profile
            if len(self.printers) == 1:
                self.current_printer_profile_guid = new_profile.guid
        elif profile_type == "Stabilization":
            new_profile = StabilizationSettings(profile)
            self.stabilizations[guid] = new_profile
        elif profile_type == "Snapshot":
            new_profile = SnapshotSettings(profile)
            self.snapshots[guid] = new_profile
        elif profile_type == "Rendering":
            new_profile = RenderingSettings(profile)
            self.renderings[guid] = new_profile
        elif profile_type == "Camera":
            new_profile = CameraSettings(profile)
            self.cameras[guid] = new_profile
        elif profile_type == "Debug":
            new_profile = DebugProfile(self.LogFilePath, debug_profile=profile)
            self.debug_profiles[guid] = new_profile
        else:
            raise ValueError('An unknown profile type ' +
                             str(profile_type) + ' was received.')

        return new_profile

    def remove_profile(self, profile_type, guid):

        if profile_type == "Printer":
            if self.current_printer_profile_guid == guid:
                return False
            del self.printers[guid]
        elif profile_type == "Stabilization":
            if self.current_stabilization_profile_guid == guid:
                return False
            del self.stabilizations[guid]
        elif profile_type == "Snapshot":
            if self.current_snapshot_profile_guid == guid:
                return False
            del self.snapshots[guid]
        elif profile_type == "Rendering":
            if self.current_rendering_profile_guid == guid:
                return False
            del self.renderings[guid]
        elif profile_type == "Camera":
            if self.current_camera_profile_guid == guid:
                return False
            del self.cameras[guid]
        elif profile_type == "Debug":
            if self.current_debug_profile_guid == guid:
                return False
            del self.debug_profiles[guid]
        else:
            raise ValueError('An unknown profile type ' +
                             str(profile_type) + ' was received.')

        return True

    def set_current_profile(self, profile_type, guid):

        if profile_type == "Printer":
            self.current_printer_profile_guid = guid
        elif profile_type == "Stabilization":
            self.current_stabilization_profile_guid = guid
        elif profile_type == "Snapshot":
            self.current_snapshot_profile_guid = guid
        elif profile_type == "Rendering":
            self.current_rendering_profile_guid = guid
        elif profile_type == "Camera":
            self.current_camera_profile_guid = guid
        elif profile_type == "Debug":
            self.current_debug_profile_guid = guid
        else:
            raise ValueError('An unknown profile type ' +
                             str(profile_type) + ' was received.')
